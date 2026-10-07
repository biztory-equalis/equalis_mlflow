# equalis_mlflow — quick overview

## What this repo does

This repo scores the solvency ("solvabiliteit") of debtors ("verweerders") in
debt-collection cases ("dossiers"). The pipeline in `ML2Grow - inference/`:

1. **Reads** case and debtor data from Snowflake (`DOSSIERS`, `VERWEERDER`,
   and optionally `TCBB` seizure records).
2. **Builds features**: merges dossiers and debtors on `hoofddossier_id`, then
   adds age, address-stability, and payment-history features. The geo/income
   enrichment is switched off in `inference.py` (`address_enabled=False`),
   because its output was being dropped anyway (see `bugs.md`).
3. **Scores** each row with a pre-trained `RandomForestClassifier`
   (`random_forest_classifier.pkl`) and puts the probability into one of four
   "stoplight" risk levels (0–25 / 25–50 / 50–75 / 75–100 %).
4. **Writes** the results back to `DEV.INFERENCE.INFERENCE_RESULTS` in
   Snowflake.

For architecture details, see `ML2Grow - inference/CLAUDE.md`. For the full
deployment walkthrough, see `ML2Grow - inference/README.md`.

## What changed

### 1. Snowflake connection now uses key-pair auth

Snowflake requires MFA for password logins, so plain user/password no longer
works for a script that runs without anyone at the keyboard. The connection
(`ML2Grow - inference/config/snowflake_config.py`) tries these methods in
order:

| Where it runs | Auth used | What you need |
|---|---|---|
| Inside Snowpark Container Services | OAuth with the session token Snowflake injects at `/snowflake/session/token` | Nothing. Snowflake handles it. |
| Locally | **Key pair** | `SF_PRIVATE_KEY_PATH` (and `SF_PRIVATE_KEY_PASSPHRASE` if the key has one) in `.env` |
| Locally (legacy) | Password | `SF_PASSWORD` (probably blocked by MFA) |

To set up key-pair auth locally:

```bash
# generate a key pair (unencrypted here; add a passphrase if you prefer)
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

```sql
-- register the public key on your Snowflake user
-- (paste the contents of rsa_key.pub, without the BEGIN/END lines)
ALTER USER <your_user> SET RSA_PUBLIC_KEY = 'MIIBIjANBgkq...';
```

Then copy `.env.example` to `.env` and fill in `SF_*`, with
`SF_PRIVATE_KEY_PATH=./rsa_key.p8`.

> `.env`, `*.p8`, and `*.pub` are gitignored. Never commit them.

### 2. The script runs as a Snowflake container service

The script no longer runs on someone's machine. It runs inside a Docker
container on **Snowpark Container Services (SPCS)**, which is Snowflake's own
compute. The benefits:

- No separate hosting to manage.
- No credentials stored in the container, because auth uses the injected
  OAuth token.
- The data never leaves Snowflake.

The Snowflake-side setup (database/schema, image repository, grants, compute
pool, service) is in **`docs/sf_setup_container.sql`**.

## Deploying: build locally, push to Snowflake

SPCS can't build images itself. You have to **build the Docker image on your
machine** and **push it to the Snowflake image repository**. The service then
pulls the image from there.

```bash
# 0. One-time: get the registry URL of the image repository
#    (in Snowflake: SHOW IMAGE REPOSITORIES LIKE 'biztory_repo';)

# 1. Go to the folder that contains the Dockerfile
cd "ML2Grow - inference"

# 2. Build the image. --platform linux/amd64 is required:
#    SPCS runs on x86, and Apple Silicon builds arm64 by default.
docker build --rm --platform linux/amd64 \
  -t mbqxhew-ce46760.registry.snowflakecomputing.com/dev/inference/biztory_repo/inference:latest .

# 3. Log in to the Snowflake image registry (uses the key pair from above)
snow spcs image-registry login \
  --temporary-connection \
  --account mbqxhew-ce46760 \
  --user BIZTORYADMIN \
  --authenticator SNOWFLAKE_JWT \
  --private-key-file ./rsa_key.p8

# 4. Push the image to Snowflake
docker push mbqxhew-ce46760.registry.snowflakecomputing.com/dev/inference/biztory_repo/inference:latest
```

The script runs as a **job service**: it runs to completion and then stops, so
nothing sits idle and costs money. To run it with the image you just pushed,
drop the previous job and run it again. The full spec is in
`docs/sf_setup_container.sql`, section 5.

```sql
USE ROLE ANALYST;
DROP SERVICE IF EXISTS inference_job;
EXECUTE JOB SERVICE IN COMPUTE POOL biztory_pool NAME = inference_job
  FROM SPECIFICATION $$ ... $$;   -- see sf_setup_container.sql

-- check the logs
CALL SYSTEM$GET_SERVICE_LOGS('inference_job', 0, 'main', 100);
```

## TODO

- [ ] **Keep the private key out of the Docker image.** `.dockerignore` excludes
  `*.pem` and `*.key` but not `*.p8`/`*.pub`. Because the Dockerfile runs
  `COPY . .`, `rsa_key.p8` gets baked into the image that is pushed to
  Snowflake. Add `*.p8` and `*.pub` to `ML2Grow - inference/.dockerignore`.
  The container doesn't need the key anyway, because it authenticates with
  the SPCS OAuth token.
