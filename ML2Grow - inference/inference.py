# Script mirror of inference.ipynb, kept manually in sync, for headless/Docker runs.
#
# Diverges from inference.ipynb in two ways, needed to actually run (see bugs.md
# for the original notebook bugs these replace):
#   - address_enabled=False instead of True: skips the geo/income enrichment
#     step, which create_feature_set() currently discards before it reaches
#     the final dataframe anyway (see bugs.md) — same columns, ~45 min faster.
#     random_forest_classifier.pkl's feature set doesn't need the enrichment
#     columns anyway (see feature_names_in_ below).
#   - calls random_forest_classifier.predict_proba(...), not the undefined
#     `classifier`.
#
# Feature selection uses random_forest_classifier.feature_names_in_ directly
# rather than core/model_features.FEATURE_COLUMNS — that list was hand-picked
# for train_baseline_model.py's throwaway baseline model, not the real
# random_forest_classifier.pkl now in this repo (see bugs.md).
#
# Write-back to Snowflake mirrors inference.ipynb's final cell, with one fix:
# the notebook's conn_kwargs only branches on key-pair vs. password auth and
# silently drops OAuth — harmless there since the notebook is only ever run
# locally, but inference.py is what actually runs as an SPCS job, where OAuth
# (via SnowflakeConfig.use_oauth_auth) is the auth path that's taken. Calling
# connect_args() unconditionally covers all three auth methods.
from datetime import datetime, timezone

from core.data_constructor import DataConstructor
import joblib
import numpy as np
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

from config.snowflake_config import SnowflakeConfig

data_constructor = DataConstructor(TCBB_enable=False, address_enabled=False)
df = data_constructor.create_feature_set()

random_forest_classifier = joblib.load('random_forest_classifier.pkl')
# feature_names_in_ has latitude/longitude twice (an artifact of the training
# pipeline), and sklearn rejects a DataFrame with duplicate column names, so
# convert to a plain numpy array instead.
feature_names = list(random_forest_classifier.feature_names_in_)
test = df[feature_names].to_numpy()
p_solvabel = random_forest_classifier.predict_proba(test)[:, 1]
# pure prediction
# 1 = solvabel
# 0 = insolvabel

# now remap to our stoplight
stoplight = np.zeros(p_solvabel.shape, dtype=int)
stoplight[p_solvabel > 0.25] += 1
stoplight[p_solvabel > 0.5] += 1
stoplight[p_solvabel > 0.75] += 1

# 0.0 - 0.25 = level 0 => 0.62 kans insolvabel
# 0.25 - 0.5 = level 1 => 0.50 kans op insolvabel
# 0.5 - 0.75 = level 2 => 0.41 kans op insolvabel
# 0.75 - 1.0 = level 3 => 0.21 kans op insolvabel

print("Predictions:", p_solvabel.shape)
print("Stoplight level counts:", {int(level): int((stoplight == level).sum()) for level in [0, 1, 2, 3]})

# Single solvency probability + stoplight level per case, with identifying
# columns for review/export.
results = df[['hoofddossier_id', 'verweerder_id', 'verweerder']].copy()
results['p_solvabel'] = p_solvabel
results['stoplight'] = stoplight

# Write results back to Snowflake.
# TABLE_NAME / WRITE_MODE are the two things to review before running this.
TABLE_NAME = "INFERENCE_RESULTS"
SCHEMA_NAME = "INFERENCE"
DATABASE_NAME = "DEV"
WRITE_MODE = "replace"  # "append" = keep a full history of every run (adds run_timestamp)
                       # "replace" = truncate + load, table only ever holds the latest run

snowflake_config = SnowflakeConfig()

results_to_write = results.copy()
results_to_write["run_timestamp"] = datetime.now(timezone.utc)
# write_pandas maps DataFrame columns to Snowflake columns by name (upper-cased by convention)
results_to_write.columns = [c.upper() for c in results_to_write.columns]

conn_kwargs = dict(
    user=snowflake_config.user,
    account=snowflake_config.account,
    database=snowflake_config.database,
    schema=snowflake_config.schema,
    warehouse=snowflake_config.warehouse,
    role=snowflake_config.role,
)
# Covers all three auth methods: OAuth (authenticator/token), key-pair
# (private_key), or neither (empty dict, falls back to password below).
conn_kwargs.update(snowflake_config.connect_args())
if not snowflake_config.use_oauth_auth and not snowflake_config.use_key_pair_auth:
    conn_kwargs["password"] = snowflake_config.password

# write_pandas uses Snowflake's bulk PUT + COPY INTO under the hood, much faster than
# df.to_sql()'s row-by-row INSERTs for a dataframe this size.
with snowflake.connector.connect(**conn_kwargs) as conn:
    success, num_chunks, num_rows, _ = write_pandas(
        conn,
        results_to_write,
        database=DATABASE_NAME,
        schema=SCHEMA_NAME,
        table_name=TABLE_NAME,
        auto_create_table=True,
        overwrite=(WRITE_MODE == "replace"),
    )

print(f"Wrote {num_rows} rows to {TABLE_NAME} (mode='{WRITE_MODE}')")
