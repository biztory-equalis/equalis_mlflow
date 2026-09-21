"""Feature columns for the quick baseline model (see train_baseline_model.py).

Shared between training and inference so both select/encode the exact same
columns. This is NOT the original model's feature set (that pipeline lives
outside this repo, see bugs.md) — it's a minimal set picked from what
create_feature_set(address_enabled=False) reliably produces, for testing
purposes only.
"""

# Numeric columns, imputed with the median at inference/train time.
NUMERIC_COLUMNS = [
    "bedrag_weighted",
    "bedrag_cumulatief",
    "n_people_at_address",
    "estimated_leeftijd",
    "verweerder_straat_clean_nunique",
    "verweerder_postcode_nunique",
    "gevangenis_key_nunique",
    "latitude",
    "longitude",
]

# Boolean columns, imputed with the most frequent value.
BOOLEAN_COLUMNS = [
    "gerechtelijk",
    "business",
]

# Low-cardinality categorical columns, one-hot encoded.
CATEGORICAL_COLUMNS = [
    "verweerder_leeftijdscategorie",
]

FEATURE_COLUMNS = NUMERIC_COLUMNS + BOOLEAN_COLUMNS + CATEGORICAL_COLUMNS
