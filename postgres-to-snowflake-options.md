# PostgreSQL to Snowflake: Migration Options

This document details two Snowflake-native alternatives to Fivetran for replicating data from PostgreSQL into Snowflake.

---

## Option 1: Openflow Connector for PostgreSQL + Data Connectivity Proxy (DCP)

**Status:** Generally Available (GA)
**Best for:** Keeping your existing on-prem PostgreSQL and replicating data into Snowflake with no inbound firewall changes.

### Overview

Openflow is Snowflake's managed data integration platform (built on Apache NiFi). The PostgreSQL connector uses native Postgres logical replication (WAL decoding) to perform CDC and writes the data into Snowflake tables. For on-prem sources, the **Data Connectivity Proxy (DCP)** provides a secure tunnel between Snowflake and your private network.

### Architecture

```
On-prem network                          Snowflake Cloud
+------------------+                     +---------------------------+
| PostgreSQL       |                     | Openflow Runtime          |
| (port 5432)      |<--- local TCP ----->| (Snowflake-managed)       |
+------------------+                     |                           |
        ^                                | PostgreSQL CDC Connector  |
        |                                +---------------------------+
        | local network                           ^
        v                                         |
+------------------+     outbound 443     +---------------------------+
| DCP Agent        |------ TLS -------->>| Snowflake Relay           |
| (Docker, 512 MB) |     (encrypted)      | (routes TCP through      |
+------------------+                      |  mTLS tunnel)            |
                                          +---------------------------+
```

### Network / Firewall Requirements (On-Prem Side)

| Direction | Port | From / To | Purpose |
|-----------|------|-----------|---------|
| **Outbound** | 443 | DCP Agent -> Snowflake DCP endpoints | Encrypted tunnel (mTLS) to Snowflake relay |
| **Internal** | 5432 | DCP Agent -> PostgreSQL host | Agent connects to Postgres locally |
| Inbound | **None** | -- | No inbound ports need to be opened |

The DCP agent only needs:
- Linux host with Docker (or any OCI runtime)
- 1 vCPU, 512 MB RAM
- Outbound internet on port 443
- Local network access to PostgreSQL on port 5432

> **Zero-trust compatible.** Your firewall sees only outbound traffic. There is no inbound listener, no public IP, and no VPN required.

### PostgreSQL Prerequisites (On-Prem)

These are standard logical replication requirements -- likely already met if Fivetran is currently using CDC:

```sql
-- 1. Enable logical replication (requires restart)
ALTER SYSTEM SET wal_level = logical;

-- 2. Ensure enough replication slots and WAL senders
-- (at least 1 per connector instance, plus existing replication traffic)
ALTER SYSTEM SET max_replication_slots = 10;
ALTER SYSTEM SET max_wal_senders = 10;

-- 3. Create a publication for the tables to replicate
-- For PostgreSQL 13+:
CREATE PUBLICATION openflow_publication WITH (publish_via_partition_root = true);
ALTER PUBLICATION openflow_publication ADD TABLE schema_name.table_name;

-- For PostgreSQL < 13:
CREATE PUBLICATION openflow_publication;
ALTER PUBLICATION openflow_publication ADD TABLE schema_name.table_name;

-- 4. Create a replication user
CREATE USER openflow_replication WITH REPLICATION PASSWORD 'secure_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO openflow_replication;
```

Every replicated table needs either:
- A **primary key** (with REPLICA IDENTITY set to DEFAULT), or
- A **unique index** (set via `ALTER TABLE ... REPLICA IDENTITY USING INDEX ...`)

### Setup Steps

#### Step A: Set Up Openflow Deployment & Runtime

1. In Snowsight, navigate to **Ingestion > Openflow**
2. Create a Snowflake Deployment (or BYOC if preferred)
3. Create a runtime (size it based on throughput needs)

#### Step B: Set Up the Data Connectivity Proxy (for on-prem)

1. **Create a DCP object in Snowflake:**
   ```sql
   CREATE DATA CONNECTIVITY PROXY my_postgres_dcp
     ENABLED = TRUE;

   -- Issue account-level TLS certificates (wait 30 min after first call)
   SELECT SYSTEM$ISSUE_PER_ACCOUNT_CERTIFICATES();
   ```

2. **Generate a bootstrap token:**
   ```sql
   SELECT SYSTEM$GENERATE_DATA_CONNECTIVITY_PROXY_BOOTSTRAP_TOKEN('my_postgres_dcp', 7);
   ```

3. **Deploy the agent on-prem (save the token from step 2):**
   ```bash
   # Write the bootstrap token to a credentials file
   echo '<token>' > /etc/dcp-agent/secrets/dcp-bootstrap-token
   chmod 600 /etc/dcp-agent/secrets/dcp-bootstrap-token

   # Start the DCP agent container
   docker run -d \
     --name dcp-agent \
     --restart unless-stopped \
     -v /etc/dcp-agent/secrets/dcp-bootstrap-token:/etc/dcp-agent/secrets/dcp-bootstrap-token:ro \
     -e DCP_METRICS_PORT=9092 \
     -p 9092:9092 \
     snowflakedb/dcp-client:latest
   ```

4. **Verify the agent is connected:**
   ```sql
   DESCRIBE DATA CONNECTIVITY PROXY my_postgres_dcp;
   -- Check: AGENT_HEALTH = 'HEALTHY', AGENT_STATUS = 'DCP_AGENT_LIFECYCLE_CONNECTED'
   ```

5. **Create a network rule + external access integration:**
   ```sql
   -- Network rule pointing to your on-prem Postgres
   CREATE NETWORK RULE my_postgres_network_rule
     MODE = DATA_CONNECTIVITY_PROXY_EGRESS
     TYPE = HOST_PORT
     VALUE_LIST = ('my-postgres.internal.corp:5432');

   -- External access integration
   CREATE EXTERNAL ACCESS INTEGRATION my_postgres_eai
     ALLOWED_NETWORK_RULES = (my_postgres_network_rule)
     ENABLED = TRUE;

   -- Associate with the DCP object
   ALTER DATA CONNECTIVITY PROXY my_postgres_dcp
     SET EXTERNAL_ACCESS_INTEGRATIONS = (my_postgres_eai);

   -- Grant to the Openflow runtime role
   GRANT USAGE ON INTEGRATION my_postgres_eai
     TO ROLE OPENFLOW_<RUNTIME_NAME>_EXECUTE_AS_RL;
   ```

6. **Attach the EAI to the Openflow runtime** via the Openflow UI or SQL.

#### Step C: Configure the PostgreSQL Connector

1. In Snowsight: **Ingestion > Openflow > Connector Library**
2. Select **PostgreSQL CDC** connector
3. Configure with your Postgres hostname, port, credentials, publication name
4. Create a destination database in Snowflake for the replicated data
5. Start the connector

### Features

- **Snapshot + Incremental CDC:** Initial full copy, then continuous change tracking
- **Schema evolution:** Add/drop/rename columns automatically handled
- **Iceberg table destinations:** Optionally write to Snowflake-managed Iceberg tables
- **Column filtering:** Replicate only the columns you need
- **Partitioned table support:** PostgreSQL 15+ partitioned tables replicated as a single table
- **Change log / journal tables:** Full history of changes available for audit
- **Supported PostgreSQL versions:** 11 through 18 (standard, RDS, Aurora, Cloud SQL, Azure Database)

### Documentation Links

| Topic | URL |
|-------|-----|
| About Openflow Connector for PostgreSQL | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/about |
| Set up the Openflow Connector for PostgreSQL | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/setup |
| Openflow Connector: Iceberg table destinations | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/iceberg |
| Openflow Connector: Incremental replication | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/incremental-replication |
| Openflow Connector: Data mapping | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/data-mapping |
| Openflow Connector: Maintenance | https://docs.snowflake.com/en/user-guide/data-integration/openflow/connectors/postgres/maintenance |
| Configure gen 2 connector with setup wizard | https://docs.snowflake.com/en/user-guide/data-integration/openflow/gen2/setup-connector-wizard |
| Configure gen 2 connector with SQL | https://docs.snowflake.com/en/user-guide/data-integration/openflow/gen2/configure-connector-sql |
| Quickstart: gen 2 Openflow | https://docs.snowflake.com/en/user-guide/data-integration/openflow/gen2/quickstart |
| Set up Openflow - Snowflake Deployments | https://docs.snowflake.com/en/user-guide/data-integration/openflow/setup-openflow-spcs |
| Data Connectivity Proxy (overview) | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy |
| Set up Data Connectivity Proxy | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy-setup |
| DCP Reference (SQL, CLI, limitations) | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy-reference |
| DCP Security | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy-security |
| Monitor DCP | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy-monitor |
| Troubleshoot DCP | https://docs.snowflake.com/en/user-guide/data-connectivity-proxy-troubleshoot |
| Connect Openflow to private data sources via DCP | https://docs.snowflake.com/en/user-guide/data-integration/openflow/setup-openflow-spcs-dcp |

---

## Option 4: Snowflake Postgres + Data Mirroring

**Status:** Preview (Open to all accounts)
**Best for:** Consolidating your Postgres workload into Snowflake's managed platform and getting automatic, zero-infrastructure replication to Snowflake analytics tables.

### Overview

Snowflake Postgres is a fully managed PostgreSQL service running inside Snowflake. Data Mirroring continuously replicates tables from a Snowflake Postgres instance into Snowflake analytics tables using `pg_lake` (an open-source Postgres extension). No external CDC service, no connectors, no separate infrastructure.

### Architecture

```
Snowflake Platform
+--------------------------------------------------+
|                                                  |
|  Snowflake Postgres Instance                     |
|  +--------------------------------------------+  |
|  | PostgreSQL (managed VM)                     |  |
|  | - Your application data (OLTP)              |  |
|  | - pg_lake extension writes Iceberg change   |  |
|  |   logs ($changes tables)                    |  |
|  | - CDC worker captures WAL changes           |  |
|  +--------------------------------------------+  |
|           |                                      |
|           | Iceberg tables (auto-refresh, ~30s)   |
|           v                                      |
|  +--------------------------------------------+  |
|  | Snowflake Analytics Database               |  |
|  | - Target tables (materialized)              |  |
|  | - $live views (~30s lag)                    |  |
|  | - $changes tables (7-day change feed)       |  |
|  | - Serverless apply task                     |  |
|  +--------------------------------------------+  |
|                                                  |
+--------------------------------------------------+
```

### Can You Redirect Your On-Prem Readable Secondary to Snowflake Postgres?

**Yes, this is a supported scenario.** Snowflake Postgres supports **logical replication from external sources**. Here's how it would work:

1. **Create a Snowflake Postgres instance** in the same cloud region as your Snowflake account.
2. **Set up a logical replication subscription** on the Snowflake Postgres instance that subscribes to your on-prem primary PostgreSQL.
3. Your on-prem primary publishes changes, and the Snowflake Postgres instance consumes them -- effectively replacing your current readable secondary.
4. Once the Snowflake Postgres instance is caught up, **create a mirror** to replicate data into Snowflake analytics tables.

This gives you a migration path:

```
Current state:
  On-prem Primary PG ---(physical replication)---> On-prem Secondary PG (readable)

Transition state:
  On-prem Primary PG ---(logical replication)----> Snowflake Postgres Instance
                                                        |
                                                        +---(data mirroring)---> Snowflake Analytics DB

Future state (optional):
  Snowflake Postgres Instance (becomes primary) ---(data mirroring)---> Snowflake Analytics DB
```

#### Key considerations for this approach

- **Logical replication (not physical):** Snowflake Postgres uses Postgres logical replication, not streaming/physical replication. This means:
  - Your on-prem primary needs `wal_level = logical` (may already be set for Fivetran)
  - You need to create a publication on the on-prem primary
  - The Snowflake Postgres instance creates a subscription to that publication
- **Network connectivity:** Your on-prem Postgres must be reachable from Snowflake Postgres. Options:
  - **Private Link** (AWS PrivateLink or Azure Private Link) -- recommended for production
  - **Public endpoint** with firewall rules restricting to Snowflake's IP ranges
  - Snowflake Postgres instances support network policies to control ingress/egress
- **Port requirements on-prem:**
  - **Inbound port 5432** (or your PG port) must be reachable from the Snowflake Postgres instance's network
  - This is different from Option 1 (which needs no inbound ports)
- **Postgres version:** Snowflake Postgres supports versions 16-18. Your on-prem primary can be an older version, but logical replication compatibility applies.
- **Region:** Currently available on AWS and Azure only. Mirrors can't cross accounts, regions, or cloud providers.
- **Failover support:** Postgres 17+ supports logical replication failover for subscriptions created with `failover = true`.

#### Setting up the subscription on Snowflake Postgres

Using the `snowflake_admin` role on your Snowflake Postgres instance:

```sql
-- On your on-prem primary (if not already done):
CREATE PUBLICATION my_publication FOR ALL TABLES;

-- On Snowflake Postgres instance:
CREATE SUBSCRIPTION my_sub
  CONNECTION 'host=my-onprem-pg.corp.com port=5432 dbname=mydb user=repl_user password=xxx'
  PUBLICATION my_publication
  WITH (failover = true);  -- Postgres 17+ recommended
```

### Network / Firewall Requirements

For the logical replication path (on-prem -> Snowflake Postgres):

| Direction | Port | From / To | Purpose |
|-----------|------|-----------|---------|
| **Inbound** | 5432 | Snowflake Postgres -> On-prem Primary PG | Logical replication subscription |
| Outbound | -- | -- | No outbound from on-prem needed |

For the mirroring path (Snowflake Postgres -> Snowflake analytics):

| Direction | Port | From / To | Purpose |
|-----------|------|-----------|---------|
| Internal | -- | All within Snowflake | No network config needed |

> **Note:** Unlike Option 1, this approach **does require opening inbound port 5432** on your on-prem Postgres (or setting up Private Link). The trade-off is that once Snowflake Postgres is the primary, you have zero external infrastructure to manage.

### Setting Up Data Mirroring (After Snowflake Postgres Is Populated)

```sql
-- Grant permissions
GRANT APPLICATION ROLE snowflake.postgres_mirror_admin TO ROLE my_role;
GRANT USAGE ON POSTGRES INSTANCE "my_instance" TO APPLICATION snowflake;

-- Create the mirror
CALL SNOWFLAKE.POSTGRES.CREATE_MIRROR(
    mirror_name       => 'my_analytics_mirror',
    postgres_instance => 'my_instance',
    postgres_database => 'mydb',
    target_database   => 'MY_ANALYTICS_DB',
    postgres_schemas  => ['public'],
    refresh_interval  => '1 minute'
);

-- Optionally mirror to Iceberg tables
CALL SNOWFLAKE.POSTGRES.CREATE_MIRROR(
    mirror_name       => 'my_iceberg_mirror',
    postgres_instance => 'my_instance',
    postgres_database => 'mydb',
    target_database   => 'MY_ICEBERG_ANALYTICS_DB',
    postgres_schemas  => ['public'],
    refresh_interval  => '1 minute',
    target_table_type => 'ICEBERG'
);
```

### Verifying & Monitoring

```sql
-- Check mirror status
CALL SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR('my_analytics_mirror');

-- List all mirrors
SELECT * FROM TABLE(SNOWFLAKE.POSTGRES.LIST_MIRRORS());

-- Check per-table replication state (SNAPSHOTTING -> REPLICATING)
CALL SNOWFLAKE.POSTGRES.LIST_MIRRORED_TABLES('my_analytics_mirror');

-- Query the $live view for near-real-time data (~30s lag)
SELECT COUNT(*) FROM MY_ANALYTICS_DB.PUBLIC.MY_TABLE$live;

-- Query the 7-day change feed
SELECT * FROM MY_ANALYTICS_DB.PUBLIC.MY_TABLE$changes
  WHERE _snowflake_change_type = 'INSERT'
  ORDER BY _snowflake_change_commit_time DESC
  LIMIT 100;

-- Check apply task history
SELECT name, state, scheduled_time, completed_time, error_message
FROM TABLE(SNOWFLAKE.INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('hour', -24, CURRENT_TIMESTAMP()),
    RESULT_LIMIT => 100
))
WHERE name LIKE 'APPLY_MIRROR_%'
ORDER BY scheduled_time DESC;
```

### Features

- **Sub-minute latency:** ~30 seconds via `$live` views; configurable merge interval (30s to 1 day)
- **No external infrastructure:** Everything runs inside Snowflake
- **Schema evolution:** Column adds, drops, renames auto-propagated
- **Transactional apply:** Cross-table invariants (FK relationships) preserved
- **Iceberg target tables:** Optionally mirror to Snowflake-managed Iceberg tables
- **7-day change feed:** `$changes` tables expose inserts, updates, deletes
- **Exactly-once delivery:** Failed apply runs roll back and retry from the same position
- **Cost-efficient:** Delete-then-append pattern (not MERGE); insert-only batches skip target scans

### Limitations

- **Preview feature** -- not yet GA
- **AWS and Azure only** (no GCP yet)
- Mirrors can't cross accounts, regions, or cloud providers
- Source must be a Snowflake Postgres instance (not an external Postgres directly)
- Burstable tier not supported for mirroring (use STANDARD or HIGH MEMORY)
- Tables with virtual generated columns or ANSI-reserved column names can't be mirrored
- Tables without a primary key are insert-only (UPDATE/DELETE rejected at source)

### Documentation Links

| Topic | URL |
|-------|-----|
| Snowflake Postgres (overview) | https://docs.snowflake.com/en/user-guide/snowflake-postgres/about |
| Data Movement (mirroring vs pg_lake) | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-movement |
| Data Mirroring (overview) | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring |
| Create a Mirror | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-create |
| Manage and Monitor Mirrors | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-manage |
| Mirror Procedures Reference | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-reference |
| Troubleshoot Mirrors | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-troubleshooting |
| Logical Replication (external sources) | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-logical-replication |
| Snowflake Postgres Networking | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-network |
| Read Replicas | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-create-replica |
| Snowflake Postgres Mirroring Quickstart | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-create (links to quickstart) |

---

## Cost Analysis

Since you only need data refreshed **once per day**, this significantly reduces the cost for both options. Below is a breakdown of the Snowflake-side cost drivers and how to optimize them for daily-only freshness.

### Option 1: Openflow + DCP — Cost Breakdown

#### Cost components

| Component | What it is | How it's billed | Cost optimization for daily refresh |
|-----------|-----------|-----------------|--------------------------------------|
| **Openflow Management Services** | Control plane for your Openflow deployment (runs continuously) | Credits per compute-hour (SPCS compute pool). Runs **as long as the deployment is active**, even with no runtimes. | This is a fixed cost. Uses a single small compute pool node. |
| **Openflow Runtime** | The compute that runs the PostgreSQL CDC connector | Credits per compute-hour (SPCS compute pool). Billed per-second with 5-minute minimum. Scales to 0 when all runtimes are stopped. | **Key savings lever.** You can stop the runtime when not in use. For daily refresh: run for a window, then stop. |
| **Warehouse (for snapshot/merge)** | CDC connectors require a warehouse for initial snapshot and periodic MERGE operations | Standard warehouse credits (e.g., XS = 1 credit/hour) | Use an XS warehouse. Schedule MERGE operations to batch changes. |
| **Snowflake storage** | Replicated tables + journal/change-log tables | Standard Snowflake storage rates (~$23-$40/TB/month depending on edition/region) | Proportional to data volume. No optimization needed. |
| **DCP Agent** | Runs on your on-prem infrastructure | **No Snowflake cost** — runs on your hardware | Only costs you the Docker host (1 vCPU, 512 MB). |

#### Daily refresh strategy

The Openflow PostgreSQL connector is designed for **continuous CDC** — it keeps a persistent replication slot open on PostgreSQL and streams changes continuously. You have two approaches for daily-only freshness:

**Approach A: Run continuously but merge daily (recommended)**
- Keep the Openflow runtime and connector running 24/7 (changes stream continuously)
- Schedule the MERGE into destination tables to run **once per day**
- This keeps the replication slot healthy and avoids re-snapshotting
- Cost: Runtime runs 24/7 (small node), but warehouse only spins up for daily merge

**Approach B: Run the connector on a schedule**
- Stop the Openflow runtime after each daily sync completes
- Restart it the next day
- Risk: The PostgreSQL replication slot may be invalidated if WAL is cleaned up during downtime
- This can force a full re-snapshot, which is more expensive than continuous CDC

> **Recommendation:** Approach A is safer and likely cheaper in the long run. A small Openflow runtime running 24/7 costs less than repeated re-snapshots from lost replication slots.

#### Estimated daily cost (Approach A — continuous CDC, daily merge)

| Component | Estimate | Notes |
|-----------|----------|-------|
| Openflow Management Services | ~2-4 credits/day | Single small compute pool node, runs 24/7 |
| Openflow Runtime (small, 1 node) | ~2-4 credits/day | Continuous CDC streaming, small runtime |
| Warehouse (XS, daily merge) | ~0.1-0.5 credits/day | XS warehouse for ~5-30 min merge window |
| Storage | Variable | Standard Snowflake storage rates per TB |
| **Total Snowflake compute** | **~4-9 credits/day** | Excludes storage |

> **Note:** Exact credit rates depend on your Snowflake edition and contract. Credit rates for Openflow Snowflake Deployment compute are listed in the [Snowflake Service Consumption Table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf). The numbers above are rough estimates — query `OPENFLOW_USAGE_HISTORY` and `SERVERLESS_TASK_HISTORY` after setup to see actual usage.

#### How to monitor costs

```sql
-- Openflow runtime credits (BYOC deployments)
SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.OPENFLOW_USAGE_HISTORY
ORDER BY START_TIME DESC;

-- For Snowflake Deployments, check METERING_HISTORY
SELECT start_time, end_time, credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
WHERE service_type = 'OPENFLOW_COMPUTE_SNOWFLAKE'
ORDER BY start_time DESC;

-- Warehouse credits used for merge operations
SELECT start_time, end_time, warehouse_name, credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'OPENFLOW_MERGE_WH'
ORDER BY start_time DESC;
```

---

### Option 4: Snowflake Postgres + Mirroring — Cost Breakdown

#### Cost components

| Component | What it is | How it's billed | Cost optimization for daily refresh |
|-----------|-----------|-----------------|--------------------------------------|
| **Snowflake Postgres Instance** | The managed PostgreSQL VM | Credits per hour based on COMPUTE_FAMILY. Runs **24/7** as long as the instance exists. | This is the largest cost driver. Size appropriately. Cannot be suspended. |
| **Snowflake Postgres Storage** | Disk allocated to the instance | Flat monthly rate per TB (metered byte-month) | Allocate only what you need. Includes $changes Iceberg tables. |
| **Mirroring Apply Task** | Serverless task that merges changes into target tables | Serverless task credits (billed per-second) | **Key savings lever.** Set `refresh_interval` to `'1 day'` to run once daily. |
| **Snowflake Target Storage** | The analytics tables that mirror creates | Standard Snowflake storage rates | Proportional to data volume. |
| **Data Transfer** | Replication between PG instance and Snowflake | Standard data transfer rates | Minimal for same-region. |

#### Snowflake Postgres instance pricing

Instance pricing is based on COMPUTE_FAMILY. The instance runs 24/7 (it's a VM — you can't pause it like a warehouse). For a replication target that just receives data:

| Instance Size | Cores | Memory | Estimated credits/hour | Estimated credits/day | Use case |
|--------------|-------|--------|----------------------|---------------------|----------|
| STANDARD_M | 1 | 4 GB | Check consumption table | ~24-48 credits/day | Minimal write load (replication target only) |
| STANDARD_L | 2 | 8 GB | Check consumption table | ~48-96 credits/day | Moderate write load |
| STANDARD_XL | 4 | 16 GB | Check consumption table | ~96-192 credits/day | High write throughput |

> **Important:** The Snowflake Postgres instance is a **24/7 cost** — it doesn't suspend when idle. If you're only using it as a replication target for mirroring, use the smallest instance that can handle your write throughput. For a "readable secondary replacement" workload, STANDARD_L is typically sufficient.

> **Exact credit rates** are in the [Snowflake Service Consumption Table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf) under "Snowflake Postgres".

#### Daily refresh strategy for mirroring

Set the mirror's `refresh_interval` to `'1 day'`:

```sql
CALL SNOWFLAKE.POSTGRES.CREATE_MIRROR(
    mirror_name       => 'my_mirror',
    postgres_instance => 'my_instance',
    postgres_database => 'mydb',
    target_database   => 'MY_ANALYTICS_DB',
    postgres_schemas  => ['public'],
    refresh_interval  => '1 day'    -- merge once per day
);
```

With a 1-day interval:
- The CDC worker still captures changes continuously (this is necessary to keep the replication slot healthy)
- Changes accumulate in `$changes` Iceberg tables
- The serverless apply task runs **once per day**, merging all accumulated changes in a single batch
- The `$live` view still provides ~30-second freshness if you ever need it ad-hoc (no extra cost — it reads from $changes directly)

> **This is the cheapest mirroring configuration.** A larger refresh_interval means fewer apply runs, and each run batches more changes into a single MERGE operation (less compute per change).

#### Estimated daily cost

| Component | Estimate | Notes |
|-----------|----------|-------|
| Snowflake Postgres Instance (STANDARD_L) | ~48-96 credits/day | 24/7, cannot be suspended. Biggest cost. |
| Mirroring Apply Task (1x/day) | ~0.01-1 credits/day | Single serverless task run, scales with data volume |
| Postgres Storage (instance-side) | Variable | $changes + metalog Iceberg tables |
| Snowflake Target Storage | Variable | Standard Snowflake storage rates |
| **Total Snowflake compute** | **~50-100 credits/day** | Dominated by the Postgres instance |

#### How to monitor costs

```sql
-- Snowflake Postgres compute credits
SELECT *
FROM SNOWFLAKE.ACCOUNT_USAGE.POSTGRES_COMPUTE_USAGE_HISTORY
ORDER BY START_TIME DESC;

-- Or via metering history
SELECT start_time, end_time, credits_used
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
WHERE service_type IN ('POSTGRES_COMPUTE', 'POSTGRES_COMPUTE_HA')
ORDER BY start_time DESC;

-- Snowflake Postgres storage
SELECT *
FROM SNOWFLAKE.ACCOUNT_USAGE.POSTGRES_STORAGE_USAGE_HISTORY
ORDER BY START_TIME DESC;

-- Mirroring apply task credits
SELECT *
FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY
WHERE TASK_NAME LIKE 'APPLY_MIRROR_%'
ORDER BY START_TIME DESC;

-- Target database storage
SELECT *
FROM SNOWFLAKE.ACCOUNT_USAGE.DATABASE_STORAGE_USAGE_HISTORY
WHERE DATABASE_NAME = 'MY_ANALYTICS_DB'
ORDER BY USAGE_DATE DESC;
```

---

### Cost Comparison Summary

Given your scenario: **continuous source changes, daily refresh needed in Snowflake.**

| Cost driver | Option 1: Openflow + DCP | Option 4: Snowflake Postgres + Mirroring |
|-------------|--------------------------|------------------------------------------|
| **Snowflake compute (daily)** | ~4-9 credits/day | ~50-100 credits/day |
| **24/7 fixed cost?** | Yes (management pool + runtime) but small | Yes (Postgres instance) and significant |
| **Can scale to zero?** | Runtime can stop (but risks replication slot) | Instance cannot be suspended |
| **Per-refresh cost** | Warehouse for MERGE (~0.1-0.5 credits) | Serverless task (~0.01-1 credits) |
| **Storage** | Standard Snowflake rates | Postgres storage + Snowflake storage |
| **Fivetran license saved** | Yes | Yes |
| **On-prem infra cost** | DCP agent host (minimal) | None (after migration) |
| **Primary cost driver** | Openflow runtime (small) | Snowflake Postgres instance (24/7 VM) |

> **Bottom line on cost:** Option 1 is significantly cheaper on the Snowflake side (~5-10x less daily compute) because it doesn't require running a full Postgres VM 24/7. The Openflow runtime is a lightweight container that costs far less than a dedicated database instance.
>
> Option 4's cost makes more sense if you're also using Snowflake Postgres as your **production OLTP database** (replacing on-prem Postgres entirely), so the instance cost serves double duty. If you're running it purely as a replication target, it's expensive for daily-only analytics.

### Cost Documentation Links

| Topic | URL |
|-------|-----|
| Snowflake Service Consumption Table (credit rates) | https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf |
| Understanding Compute Cost | https://docs.snowflake.com/en/user-guide/cost-understanding-compute |
| Exploring Compute Cost | https://docs.snowflake.com/en/user-guide/cost-exploring-compute |
| Openflow Snowflake Deployment Cost | https://docs.snowflake.com/en/user-guide/data-integration/openflow/cost-spcs |
| Openflow BYOC Cost | https://docs.snowflake.com/en/user-guide/data-integration/openflow/cost-byoc |
| Snowflake Postgres Cost Evaluation | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-cost |
| Snowflake Postgres Instance Sizes | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-instance-sizes |
| Understanding Mirroring Costs | https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring#understanding-mirroring-costs |
| OPENFLOW_USAGE_HISTORY View | https://docs.snowflake.com/en/sql-reference/account-usage/openflow_usage_history |
| SERVERLESS_TASK_HISTORY View | https://docs.snowflake.com/en/sql-reference/account-usage/serverless_task_history |
| POSTGRES_COMPUTE_USAGE_HISTORY View | https://docs.snowflake.com/en/sql-reference/account-usage/postgres_compute_usage_history |
| POSTGRES_STORAGE_USAGE_HISTORY View | https://docs.snowflake.com/en/sql-reference/account-usage/postgres_storage_usage_history |

---

## Side-by-Side Comparison

| Aspect | Option 1: Openflow + DCP | Option 4: Snowflake Postgres + Mirroring |
|--------|--------------------------|------------------------------------------|
| **Maturity** | GA | Preview |
| **On-prem Postgres stays?** | Yes -- no changes to your DB | No -- migrate to Snowflake Postgres |
| **Inbound ports on-prem** | None (outbound 443 only) | 5432 (for initial logical replication sync) |
| **On-prem agent** | DCP agent (Docker, 512 MB) | None after migration completes |
| **Ongoing infrastructure** | DCP agent + Openflow runtime | Nothing -- fully managed |
| **Latency** | Near real-time CDC | ~30s via $live views |
| **Cloud availability** | AWS, Azure, GCP | AWS, Azure only |
| **Change feed** | Journal tables | 7-day $changes tables |
| **Iceberg support** | Yes (destination option) | Yes (destination option) |
| **Schema evolution** | Yes | Yes |
| **Fivetran migration effort** | Low -- swap connector, keep PG as-is | High -- migrate PG to Snowflake Postgres |
| **Long-term operational cost** | DCP agent + Openflow compute | Snowflake Postgres instance + serverless task |

### Recommendation

- **Short term / low risk:** Go with **Option 1 (Openflow + DCP)**. It drops the Fivetran dependency with minimal change to your current architecture. Your on-prem Postgres stays untouched, and the DCP agent is lighter than both Fivetran's and the old Snowflake connector agents.

- **Long term / strategic:** Evaluate **Option 4 (Snowflake Postgres + Mirroring)** as a future consolidation play. Redirecting your current readable secondary's logical replication to a Snowflake Postgres instance is a viable migration path. Once proven, you could eventually promote Snowflake Postgres to primary and eliminate on-prem Postgres entirely. Wait for GA before committing production workloads.

- **Hybrid approach:** Start with Option 1 now, and run Option 4 in parallel as a proof of concept. Both can coexist -- Option 1 feeds your current analytics, while Option 4 validates the Snowflake Postgres migration path.
