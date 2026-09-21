"""Trains a quick baseline RandomForestClassifier for local testing.

This is NOT a recreation of the original random_forest_classifier.pkl (that
model was trained outside this repo — see bugs.md and CLAUDE.md). It exists
so the pipeline can be exercised end-to-end while the real model file is
unavailable. Feature choices are deliberately simple; see core/model_features.py.
"""
import joblib
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from core.data_constructor import DataConstructor
from core.model_features import (
    BOOLEAN_COLUMNS,
    CATEGORICAL_COLUMNS,
    FEATURE_COLUMNS,
    NUMERIC_COLUMNS,
)

# address_enabled=False: skips the geo/income enrichment step, which is
# currently discarded before it reaches the final dataframe anyway (see
# bugs.md) — same resulting columns, without the ~45 min it costs to compute.
print("Building feature set...")
data_constructor = DataConstructor(TCBB_enable=False, address_enabled=False)
df = data_constructor.create_feature_set()

df = df.dropna(subset=["y"])

X = df[FEATURE_COLUMNS].copy()
X[BOOLEAN_COLUMNS] = X[BOOLEAN_COLUMNS].astype(int)
y = df["y"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

preprocessor = ColumnTransformer(
    [
        ("num", SimpleImputer(strategy="median"), NUMERIC_COLUMNS),
        ("bool", SimpleImputer(strategy="most_frequent"), BOOLEAN_COLUMNS),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLUMNS),
    ]
)

model = Pipeline(
    [
        ("preprocess", preprocessor),
        (
            "clf",
            RandomForestClassifier(
                n_estimators=200,
                max_depth=12,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ]
)

print(f"Training on {len(X_train)} rows, evaluating on {len(X_test)} rows...")
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
y_proba = model.predict_proba(X_test)[:, 1]

print("Accuracy:", accuracy_score(y_test, y_pred))
print("ROC AUC:", roc_auc_score(y_test, y_proba))
print(classification_report(y_test, y_pred))

joblib.dump(model, "random_forest_classifier.pkl")
print("Saved random_forest_classifier.pkl")
