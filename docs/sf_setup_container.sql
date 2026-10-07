-- Alter the user we are going to use to store the container with a key pair
use role accountadmin;

-- ============================================================
-- 0. Context (adjust role/db/schema/warehouse to your account)
-- ============================================================
USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS dev;
CREATE SCHEMA IF NOT EXISTS inference;
USE DATABASE DEV;
USE SCHEMA INFERENCE;

CREATE WAREHOUSE IF NOT EXISTS inference_wh
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

-- ============================================================
-- 1. Image repository (holds your Docker image)
-- ============================================================
DROP IMAGE REPOSITORY biztory_repo;
CREATE IMAGE REPOSITORY IF NOT EXISTS biztory_repo;

-- Get the registry URL you'll push to, e.g.
-- mbqxhew-ce46760.registry.snowflakecomputing.com/demo_db/public/demo_repo
SHOW IMAGE REPOSITORIES LIKE 'biztory_repo';
SHOW IMAGES IN IMAGE REPOSITORY dev.inference.biztory_repo;
SHOW GRANTS ON IMAGE REPOSITORY dev.inference.biztory_repo;
grant read on IMAGE REPOSITORY dev.inference.biztory_repo to role ANALYST;

-- ============================================================
-- 2. Compute pool (the actual container infrastructure)
-- ============================================================
SHOW COMPUTE POOL INSTANCE FAMILIES;
SHOW COMPUTE POOLS;
DESCRIBE COMPUTE POOL biztory_pool;

USE ROLE SYSADMIN;
CREATE COMPUTE POOL IF NOT EXISTS biztory_pool
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_S
  AUTO_RESUME = TRUE
  AUTO_SUSPEND_SECS = 300;

DROP COMPUTE POOL IF EXISTS biztory_pool;

ALTER COMPUTE POOL biztory_pool SUSPEND;
ALTER COMPUTE POOL biztory_pool SET INSTANCE_FAMILY = CPU_X64_S;
ALTER COMPUTE POOL biztory_pool RESUME;

DESCRIBE COMPUTE POOL BIZTORY_POOL;


GRANT USAGE ON COMPUTE POOL BIZTORY_POOL TO ROLE SYSADMIN;
GRANT USAGE ON COMPUTE POOL BIZTORY_POOL TO ROLE ANALYST;

-- ============================================================
-- 5. Run the job (after image is built & pushed - see README)
--    This runs to completion and stops (no idle billing).
-- ============================================================

SHOW GRANTS ON SCHEMA dev.inference;
GRANT USAGE ON SCHEMA dev.inference TO ROLE ANALYST;
GRANT CREATE SERVICE ON SCHEMA dev.inference TO ROLE ANALYST;  

USE ROLE SYSADMIN;
USE ROLE ANALYST;
DROP SERVICE inference_job;

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

-- ============================================================
-- 6. Check results
-- ============================================================
SHOW SERVICES;

SHOW SERVICE CONTAINERS IN SERVICE inference_job;

SHOW SERVICES IN COMPUTE POOL biztory_pool;
SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
SHOW SERVICE INSTANCES IN SERVICE inference_job;
SHOW SERVICE CONTAINERS IN SERVICE inference_job;

show grants on service inference_job;
grant monitor on service inference_job to role SYSADMIN;
SHOW SERVICE CONTAINERS IN SERVICE inference_job;
CALL SYSTEM$GET_SERVICE_LOGS('inference_job', 0, 'main', 100);

