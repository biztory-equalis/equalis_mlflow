# Script mirror of inference.ipynb, kept manually in sync, for headless/Docker runs.
#
# Diverges from inference.ipynb in three ways, needed to actually run against
# train_baseline_model.py's model (see bugs.md for the original notebook bugs
# these replace):
#   - address_enabled=False instead of True: skips the geo/income enrichment
#     step, which create_feature_set() currently discards before it reaches
#     the final dataframe anyway (see bugs.md) — same columns, ~45 min faster.
#   - feature selection uses the explicit core/model_features.FEATURE_COLUMNS
#     list (shared with training) instead of "all columns minus one", which
#     included raw IDs/strings/dates the model can't consume.
#   - calls random_forest_classifier.predict_proba(...), not the undefined
#     `classifier`.
from core.data_constructor import DataConstructor
from core.model_features import BOOLEAN_COLUMNS, FEATURE_COLUMNS
import joblib
import numpy as np

data_constructor = DataConstructor(TCBB_enable=False, address_enabled=False)
df = data_constructor.create_feature_set()

test = df[FEATURE_COLUMNS].copy()
test[BOOLEAN_COLUMNS] = test[BOOLEAN_COLUMNS].astype(int)
random_forest_classifier = joblib.load('random_forest_classifier.pkl')
y_hat = random_forest_classifier.predict_proba(test)[:, 1]
# pure prediction
# 1 = solvabel
# 0 = insolvabel

# now remap to our stoplight
y_step = np.zeros(y_hat.shape)
y_step[y_hat > 0.25] += 1
y_step[y_hat > 0.5] += 1
y_step[y_hat > 0.75] += 1

# 0.0 - 0.25 = level 0 => 0.62 kans insolvabel
# 0.25 - 0.5 = level 1 => 0.50 kans op insolvabel
# 0.5 - 0.75 = level 2 => 0.41 kans op insolvabel
# 0.75 - 1.0 = level 3 => 0.21 kans op insolvabel

print("Predictions:", y_hat.shape)
print("Stoplight level counts:", {int(level): int((y_step == level).sum()) for level in [0, 1, 2, 3]})
