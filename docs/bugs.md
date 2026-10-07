# Known bugs

## Geo/income enrichment discarded in `create_feature_set` (address_enabled path)

**File:** `core/data_constructor.py:175-179`

```python
feature_df = self.datacollector.enrich_data_point_v2(verweerder_features)

feature_df = dossier_features.merge(
    verweerder_features, on=["hoofddossier_id"], how="left"
)
```

`enrich_data_point_v2(verweerder_features)` computes the geo/statistical-sector/income
enrichment (Lambert72 coordinates, sector info, income stats) and assigns it to
`feature_df`. The very next statement immediately overwrites `feature_df` by merging
`dossier_features` with the original, un-enriched `verweerder_features` instead of the
enriched result. The enrichment output is silently discarded.

**Effect:** with `address_enabled=True`, `create_feature_set()` returns 44 columns
instead of the 51 documented in `inference.ipynb`'s markdown cell — missing
`X_Lambert72`, `Y_Lambert72`, `geometry`, `CD_YEAR`, `CD_MUNTY_REFNIS`, `CD_SECTOR`,
`MS_NBR_NON_ZERO_INC`, `MS_TOT_NET_TAXABLE_INC`, `MS_AVG_TOT_NET_TAXABLE_INC`,
`MS_MEDIAN_NET_TAXABLE_INC`, `MS_INT_QUART_DIFF`, `MS_INT_QUART_COEFF`,
`MS_INT_QUART_ASSYM`, `TX_SECTOR_DESCR_NL`, `TX_SECTOR_DESCR_FR`.

The enrichment step itself is expensive (~45 min for ~1.18M rows via
`DataCollecter.enrich_data_point_v2`'s row-wise sector/income lookup), so this bug
means that time is spent computing a result that then gets thrown away.

**Likely fix:** merge the enriched dataframe instead of the original, e.g.:

```python
feature_df = self.datacollector.enrich_data_point_v2(verweerder_features)

feature_df = dossier_features.merge(
    feature_df, on=["hoofddossier_id"], how="left"
)
```

**Found:** 2026-09-21, while running the pipeline end-to-end for the first time after
setting up key-pair Snowflake auth and a fresh `uv`-managed venv. Confirmed via an
actual run: `create_feature_set(TCBB_enable=False, address_enabled=True)` returned
`(1925098, 44)` with no enrichment columns present.

## Undefined `classifier` variable / missing model file in `inference.ipynb`

**File:** `inference.ipynb`, model-inference cell (still present — the notebook itself
was intentionally left untouched)

```python
random_forest_classifier = joblib.load('random_forest_classifier.pkl')
y_hat = classifier.predict_proba(test)
```

`classifier` is never defined — only `random_forest_classifier` is. This looks like a
leftover from a rename. Also, the `test = df[columns]` feature selection just above it
drops one label column and passes everything else (IDs, raw strings, dates) straight
into `predict_proba`, which no real sklearn model can consume as-is.

**Found:** 2026-09-21, while reviewing the notebook before a test run.

**Status:** worked around in `inference.py` (the headless script mirror), which fixes
both the `classifier` typo and the feature selection (now uses the explicit
`core/model_features.FEATURE_COLUMNS` list, shared with `train_baseline_model.py`).
`inference.ipynb` itself was left as-is per the original ask to keep it. The real
`random_forest_classifier.pkl` was still never found — see the new entry below for what
unblocked local testing instead.

## No real `random_forest_classifier.pkl` available

The original pre-trained model (whatever produced the "0.21 kans op insolvabel" style
comments in `inference.ipynb`) was never found in this checkout and its training
pipeline lives outside this repo (see "where does training data come from" discussion —
no `.fit(`/`train_test_split`/`mlflow` usage anywhere here).

**Workaround for local testing:** `train_baseline_model.py` trains a quick,
from-scratch `RandomForestClassifier` on the real Snowflake data using a small, hand-picked
feature set (`core/model_features.py`) — bedrag features, address-stability counts,
estimated age, lat/long, business flag, age bracket. No hyperparameter tuning, no
attempt to match the original's methodology. Quick baseline result: ~0.68 accuracy,
~0.76 ROC AUC on a 20% holdout. This exists purely to unblock exercising the pipeline
end-to-end (`inference.py`) — it should **not** be treated as a real production model.
Whoever has the original training pipeline/model should still be tracked down.

**Found / added:** 2026-09-21.
