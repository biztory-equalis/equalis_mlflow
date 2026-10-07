# ML2Grow Inference — Snowpark Container Services Deployment

This document describes how the inference pipeline is packaged and run as a
**Snowpark Container Services (SPCS)** job, and what the pipeline does once
it's running.

All Snowflake SQL referenced below is collected in
[`docs/sf_setup_container.sql`](../docs/sf_setup_container.sql). For a short
overview of the repo and recent changes, see [`docs/docs.md`](../docs/docs.md).

## Table of contents

1. [What this process does](#1-what-this-process-does)
2. [Authentication (key pair / OAuth)](#2-authentication-key-pair--oauth)
3. [Setup the container services in Snowflake](#3-setup-the-container-services-in-snowflake)
4. [Build and push the Docker image](#4-build-and-push-the-docker-image)
5. [Create the compute pool](#5-create-the-compute-pool)
6. [Run the job service](#6-run-the-job-service)
7. [Checking the results](#7-checking-the-results)
8. [Running locally](#8-running-locally)
9. [TODO](#9-todo)

---

## 1. What this process does

The pipeline starts and ends in Snowflake. The ML scoring happens in between,
inside a container that runs on Snowflake's own compute (SPCS):

```
Snowflake (source tables)  -->  ML inference container (SPCS)  -->  Snowflake (DEV.INFERENCE.INFERENCE_RESULTS)
```

The container runs `inference.py`, which is the Dockerfile's `CMD`. It is the
script version of `inference.ipynb`, and you have to keep the two in sync by
hand.

**Step by step:**

1. **Read from Snowflake.** The container connects to Snowflake with the
   OAuth session token that SPCS injects into every running container, so no
   credentials are stored in it. It reads the debt-collection case data:
   - `DOSSIERS`: the cases ("dossiers").
   - `VERWEERDER`: the debtors ("verweerders", i.e. defendants) linked to
     each case.
   - `TCBB`: seizure ("beslag") records. These are only read when
     `TCBB_enable=True`, and it is off in `inference.py`.

2. **Build features.** `DataConstructor.create_feature_set()` merges dossier
   and debtor data on `hoofddossier_id`, then derives debtor age,
   address-stability, and payment-history features. Latitude and longitude
   come from a static postcode lookup, not live geocoding.

   `inference.py` runs with `address_enabled=False`, which skips the
   geo/income enrichment step. Its output was being thrown away before it
   reached the final dataframe anyway (see `bugs.md`), and skipping it saves
   about 45 minutes. The model only uses the columns listed in
   `random_forest_classifier.feature_names_in_`.

3. **Score with the model.** A pre-trained `RandomForestClassifier`
   (`random_forest_classifier.pkl`, trained outside this repo) predicts
   `p_solvabel`, the probability that a debtor is solvent. Each prediction is
   placed in one of four "stoplight" levels:

   | `p_solvabel` | `stoplight` | Meaning |
   |---|---|---|
   | 0.00 – 0.25 | 0 | Red (low solvency) |
   | 0.25 – 0.50 | 1 | Orange |
   | 0.50 – 0.75 | 2 | Yellow |
   | 0.75 – 1.00 | 3 | Green (high solvency) |

4. **Write back to Snowflake.** The results are written with `write_pandas`
   to `DEV.INFERENCE.INFERENCE_RESULTS`. The table has these columns:
   `HOOFDDOSSIER_ID`, `VERWEERDER_ID`, `VERWEERDER`, `P_SOLVABEL`,
   `STOPLIGHT`, `RUN_TIMESTAMP`. The table is created automatically. By
   default (`WRITE_MODE = "replace"`) each run overwrites the previous one.
   Set `WRITE_MODE = "append"` in `inference.py` to keep a history of every
   run.

**Why SPCS instead of a plain Python job somewhere else?**
- No separate hosting to manage. Snowflake provisions the compute pool.
- Authentication uses the injected OAuth token, so there are no credentials
  to distribute or rotate for the running job.
- Data never leaves Snowflake's security boundary for scoring.

## 2. Authentication (key pair / OAuth)

Snowflake requires MFA for password logins, so password auth no longer works
for a script that runs without anyone at the keyboard. `SnowflakeConfig`
(`config/snowflake_config.py`) picks the auth method automatically:

| Where it runs | Auth used | What you need |
|---|---|---|
| Inside SPCS | OAuth, using the token at `/snowflake/session/token` | Nothing. `SNOWFLAKE_ACCOUNT`/`SNOWFLAKE_HOST` are injected, and database, schema, warehouse, and role are set in the service spec. |
| Locally | **Key pair** | `SF_PRIVATE_KEY_PATH` (plus `SF_PRIVATE_KEY_PASSPHRASE` if the key is encrypted) in `.env` |
| Locally (legacy) | Password | `SF_PASSWORD` (most likely blocked by MFA) |

You also need the key pair to log in to the Snowflake image registry when you
push the Docker image ([section 4](#4-build-and-push-the-docker-image)).

Generate a key pair and register it on your Snowflake user:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

```sql
USE ROLE ACCOUNTADMIN;
-- paste the contents of rsa_key.pub without the BEGIN/END lines
ALTER USER <your_user> SET RSA_PUBLIC_KEY = 'MIIBIjANBgkq...';
```

`.env`, `*.p8`, and `*.pub` are gitignored. Never commit them.

## 3. Setup the container services in Snowflake

- Create the database, schema, and warehouse used by the job.
```sql
USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS dev;
CREATE SCHEMA IF NOT EXISTS inference;
USE DATABASE DEV;
USE SCHEMA INFERENCE;

CREATE WAREHOUSE IF NOT EXISTS inference_wh
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;
```
- Create an **image repository** to hold the Docker image.
```sql
CREATE IMAGE REPOSITORY IF NOT EXISTS biztory_repo;
```
- Get the registry URL you'll push to. You need it in
  [section 4](#4-build-and-push-the-docker-image), e.g.
  `mbqxhew-ce46760.registry.snowflakecomputing.com/dev/inference/biztory_repo`.
```sql
SHOW IMAGE REPOSITORIES LIKE 'biztory_repo';
```
- Grant the needed rights. For now the service runs under the **ANALYST**
  role, because that role already has access to all the data.
```sql
GRANT READ ON IMAGE REPOSITORY dev.inference.biztory_repo TO ROLE ANALYST;
GRANT USAGE ON SCHEMA dev.inference TO ROLE ANALYST;
GRANT CREATE SERVICE ON SCHEMA dev.inference TO ROLE ANALYST;
```

## 4. Build and push the Docker image

SPCS can't build images itself. You **build the image on your machine** and
**push it to the Snowflake image repository**, and the job pulls it from
there.

- Build the image from the `Dockerfile` in this folder.
  `--platform linux/amd64` is required: SPCS runs on x86, and Apple Silicon
  builds arm64 by default.
```bash
# go into the folder where the Dockerfile is located
cd "ML2Grow - inference"

docker build --rm --platform linux/amd64 \
  -t mbqxhew-ce46760.registry.snowflakecomputing.com/dev/inference/biztory_repo/inference:latest .
```
- Log in to the Snowflake image registry with the key pair from
  [section 2](#2-authentication-key-pair--oauth).
```bash
snow spcs image-registry login \
  --temporary-connection \
  --account mbqxhew-ce46760 \
  --user BIZTORYADMIN \
  --authenticator SNOWFLAKE_JWT \
  --private-key-file ./rsa_key.p8
```
- Push the image to the Snowflake image repository.
```bash
docker push mbqxhew-ce46760.registry.snowflakecomputing.com/dev/inference/biztory_repo/inference:latest
```
- Check that the image arrived.
```sql
SHOW IMAGES IN IMAGE REPOSITORY dev.inference.biztory_repo;
```

## 5. Create the compute pool

The compute pool is the machine the container runs on.

```sql
USE ROLE SYSADMIN;

CREATE COMPUTE POOL IF NOT EXISTS biztory_pool
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_S
  AUTO_RESUME = TRUE
  AUTO_SUSPEND_SECS = 300;

GRANT USAGE ON COMPUTE POOL biztory_pool TO ROLE ANALYST;
```

## 6. Run the job service

The pipeline runs as a **job service**: it runs to completion and then stops,
so there is no idle billing. A job name can't be reused, so drop the previous
run first. Run this again every time you push a new image.

```sql
USE ROLE ANALYST;
DROP SERVICE IF EXISTS inference_job;

EXECUTE JOB SERVICE
  IN COMPUTE POOL biztory_pool
  NAME = inference_job
  FROM SPECIFICATION $$
  spec:
    containers:
      - name: main
        image: /dev/inference/biztory_repo/inference:latest
        env:
            SNOWFLAKE_WAREHOUSE: WH_ANALYST
            SNOWFLAKE_DATABASE: DEV
            SNOWFLAKE_SCHEMA: REPORTING
            SNOWFLAKE_ROLE: ANALYST
  $$;
```

`SNOWFLAKE_DATABASE`/`SNOWFLAKE_SCHEMA` point to where the **source** tables
live (`DEV.REPORTING`). The results table location
(`DEV.INFERENCE.INFERENCE_RESULTS`) is hardcoded in `inference.py`.

## 7. Checking the results

- Status of the job:
```sql
SHOW SERVICES IN COMPUTE POOL biztory_pool;
SHOW SERVICE CONTAINERS IN SERVICE inference_job;
```
- Container logs (the last 100 lines of the `main` container). This is where
  the `print` output of `inference.py` shows up, e.g. the stoplight counts
  and `Wrote N rows to INFERENCE_RESULTS`.
```sql
CALL SYSTEM$GET_SERVICE_LOGS('inference_job', 0, 'main', 100);
```
- The scored output:
```sql
SELECT * FROM DEV.INFERENCE.INFERENCE_RESULTS;

SELECT STOPLIGHT, COUNT(*) FROM DEV.INFERENCE.INFERENCE_RESULTS GROUP BY STOPLIGHT ORDER BY STOPLIGHT;
```

## 8. Running locally

```bash
cd "ML2Grow - inference"
pip install -r requirements.txt
cp .env.example .env   # fill in SF_* and SF_PRIVATE_KEY_PATH
python inference.py    # or work interactively in inference.ipynb
```

Locally, query results are cached as parquet snapshots in `data/`. See
`CLAUDE.md` for how the cache works.

## 9. TODO

- [ ] **Keep the private key out of the Docker image.** `.dockerignore`
  doesn't exclude `*.p8`/`*.pub`, and the Dockerfile runs `COPY . .`, so
  `rsa_key.p8` gets baked into the image pushed to Snowflake. Add `*.p8` and
  `*.pub` to `.dockerignore`. The container authenticates with the SPCS
  OAuth token and doesn't need the key.
- [ ] `sql/dossiers_query.sql` only selects *concluded* dossiers (the filter
  the training needed). For real inference it has to select open dossiers.
  See `CLAUDE.md`.
