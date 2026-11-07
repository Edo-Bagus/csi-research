"""
Per-class MAE comparison: Random Forest vs CNN-LSTM (regression).

The per-class MAE is derived from the confusion matrix aggregated across the 4
outer folds. For regression the predictions are rounded to integer person
counts, so for a given true class k:

    MAE(k) = sum_j  cm[k, j] * |k - j|  /  sum_j cm[k, j]

i.e. the average distance between the true count k and the predicted count,
weighted by how many windows landed in each predicted bin. A class with all
its mass on the diagonal has MAE 0 (no bar).

A grouped bar chart shows the two models side by side per class.

Output: final_result/mae_per_class.png  (and .svg)

Run:
    python result/plot_mae_per_class.py
"""

import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "final_result"
RF_FILE = RESULT_DIR / "reg" / "nested_cv_result_rf_reg.json"
CNN_LSTM_FILE = RESULT_DIR / "reg" / "nested_cv_result_cnn_lstm_reg.json"
OUT_PATH = RESULT_DIR / "mae_per_class.png"

RF_COLOR = "#7f7f7f"        # grey
CNN_LSTM_COLOR = "#1f77b4"  # blue

# Bigger text everywhere.
plt.rcParams.update({
    "font.size": 18,
    "axes.titlesize": 22,
    "axes.labelsize": 20,
    "xtick.labelsize": 17,
    "ytick.labelsize": 17,
    "legend.fontsize": 18,
})


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def per_class_mae(path: Path) -> np.ndarray:
    """MAE per true class from the confusion matrix summed over outer folds."""
    data = json.loads(path.read_text())
    cm = np.sum(
        [
            np.asarray(f["outer_val_metrics"]["confusion_matrix"], dtype=float)
            for f in data["outer_folds"]
        ],
        axis=0,
    )
    n = cm.shape[0]
    idx = np.arange(n)
    row_sums = cm.sum(axis=1)
    mae = np.array([
        (cm[i] * np.abs(idx - i)).sum() / row_sums[i] if row_sums[i] else 0.0
        for i in range(n)
    ])
    return mae


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
def main():
    rf_mae = per_class_mae(RF_FILE)
    cl_mae = per_class_mae(CNN_LSTM_FILE)

    n = len(rf_mae)
    classes = np.arange(n)          # person counts 0..n-1
    width = 0.38

    fig, ax = plt.subplots(figsize=(12, 7.5))

    ax.bar(classes - width / 2, rf_mae, width,
           label="Random Forest", color=RF_COLOR)
    ax.bar(classes + width / 2, cl_mae, width,
           label="CNN-LSTM", color=CNN_LSTM_COLOR)

    ax.set_xlabel("Kelas (jumlah orang)")
    ax.set_ylabel("MAE per kelas")
    ax.set_xticks(classes)
    ax.set_xticklabels([str(c) for c in classes])
    ax.grid(axis="y", linestyle="-", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(frameon=True)

    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=400, bbox_inches="tight")
    fig.savefig(OUT_PATH.with_suffix(".svg"), bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")
    print(f"Saved: {OUT_PATH.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
