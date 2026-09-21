import math
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix
from urllib3.util.retry import Retry


def convert_age_to_date(years):
    date_str = datetime.today().strftime("%Y-%m-%d")

    # Convert to datetime object
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")

    # Add 5 days
    date_plus_5 = date_obj + timedelta(days=5)

    # Subtract X years
    final_date = date_plus_5 - relativedelta(years=years)

    return final_date.strftime("%Y-%m-%d")


def leeftijdscategorie_to_number(value: str) -> int:
    if value.strip() == "100 +":
        return 105  # or any representative value for 100+

    # Handle ranges like "21 - 30"
    try:
        parts = value.split("-")
        if len(parts) == 2:
            start = int(parts[0].strip())
            end = int(parts[1].strip())
            return (start + end) // 2
    except ValueError:
        pass  # In case of unexpected input

    raise ValueError(f"Invalid leeftijdscategorie: {value}")


def is_valid_number(x):
    if x is None:
        return False
    try:
        # Convert to float to catch 'NaN' strings or invalid values
        return not math.isnan(float(x))
    except (ValueError, TypeError) as e:
        print(e)
        return False


def get_leeftijd(leeftijd: str, leeftijdscategorie: str) -> str:
    if is_valid_number(leeftijd):
        leeftijd_num = int(leeftijd)
    else:
        leeftijdscategorie_num = leeftijdscategorie_to_number(leeftijdscategorie)
        leeftijd_num = (
            leeftijdscategorie_num if is_valid_number(leeftijdscategorie_num) else 0
        )

    return leeftijd_num


def get_geboortedatum(leeftijd: int) -> str:
    return convert_age_to_date(leeftijd)


def send_request(username, password, request_body, endpoint):
    url = "https://equalis.ml2grow.cloud" + endpoint

    response = requests.post(
        url, json=request_body, auth=HTTPBasicAuth(username, password)
    )

    return response


def send_request_retry(username, password, request_body, endpoint):
    url = "https://equalis.ml2grow.cloud" + endpoint

    session = requests.Session()

    retries = Retry(
        total=3,  # total attempts
        backoff_factor=2,  # exponential backoff (2, 4, 8 secs)
        status_forcelist=[502, 503, 504],
        allowed_methods=["POST"],  # retries on POST too
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    response = session.post(
        url, json=request_body, auth=HTTPBasicAuth(username, password)
    )
    return response


def plot_results(prediction_results):
    # Convert to DataFrame for easier processing
    df = pd.DataFrame(prediction_results).T
    df["prediction"] = df["prediction"].astype(float)
    df["is_positive"] = df["solvabiliteit"] == "Solvabel"

    # Prepare thresholds and results
    thresholds = np.linspace(0, 1, 101)
    results = []

    for threshold in thresholds:
        predicted_positive = df["prediction"] >= threshold
        predicted_negative = ~predicted_positive

        TP = (predicted_positive & df["is_positive"]).sum()
        FP = (predicted_positive & ~df["is_positive"]).sum()
        TN = (predicted_negative & ~df["is_positive"]).sum()
        FN = (predicted_negative & df["is_positive"]).sum()

        # Compute metrics
        accuracy = (TP + TN) / (TP + TN + FP + FN)
        precision = TP / (TP + FP) if TP + FP > 0 else 0
        recall = TP / (TP + FN) if TP + FN > 0 else 0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall > 0
            else 0
        )

        results.append(
            {
                "threshold": threshold,
                "TP": TP,
                "FP": FP,
                "TN": TN,
                "FN": FN,
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )

    results_df = pd.DataFrame(results)

    # Create a bar plot instead of line plot for each metric at each threshold
    fig, ax = plt.subplots(figsize=(20, 10))

    # Width of each bar group and individual bars
    bar_width = 0.2
    thresholds = results_df["threshold"]
    x = np.arange(len(thresholds))

    # Bar positions
    tp_bar = x - 1.5 * bar_width
    fp_bar = x - 0.5 * bar_width
    tn_bar = x + 0.5 * bar_width
    fn_bar = x + 1.5 * bar_width

    # Plot each bar group
    ax.bar(tp_bar, results_df["TP"], width=bar_width, label="True Positives")
    ax.bar(fp_bar, results_df["FP"], width=bar_width, label="False Positives")
    ax.bar(tn_bar, results_df["TN"], width=bar_width, label="True Negatives")
    ax.bar(fn_bar, results_df["FN"], width=bar_width, label="False Negatives")

    # Configure axes
    ax.set_xlabel("Threshold")
    ax.set_ylabel("Count")
    ax.set_title("Classification Metrics vs. Threshold (Bar Plot)")
    ax.set_xticks(x[::5])  # reduce number of x-ticks shown for readability
    ax.set_xticklabels([f"{t:.2f}" for t in thresholds[::5]], rotation=45)
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    plt.show()

    return results_df


def optimal_threshold(results_df):
    optimal_row = results_df.loc[results_df["f1"].idxmax()]
    optimal_threshold = optimal_row["threshold"]
    print(optimal_row[["accuracy", "precision", "recall", "f1"]])
    return optimal_threshold


def cf_matrix(prediction_results, threshold):
    df = pd.DataFrame(prediction_results).T
    df["prediction"] = df["prediction"].astype(float)

    y_true = df["solvabiliteit"] == "Solvabel"
    y_pred = df["prediction"] >= threshold

    cm = confusion_matrix(y_true, y_pred)
    disp = ConfusionMatrixDisplay(
        confusion_matrix=cm, display_labels=["Not Solvabel", "Solvabel"]
    )
    disp.plot()
    plt.title(f"Confusion Matrix at Threshold ({threshold:.2f})")
    plt.show()
