"""
Confusion-matrix comparison of the best classification and regression models.

For each model the per-fold confusion matrices stored in the nested-CV result
JSON are summed across all 4 outer folds, giving one aggregated matrix per
model. The two matrices are drawn side by side (1x2 grid):

  * left  : best classifier  -> 1D CNN
  * right : best regressor    -> CNN-LSTM

Each cell shows the recall (row-normalised value per true class) on top and the
raw aggregated window count in parentheses below; the colour follows the recall
so the diagonal stands out regardless of class size.

Output: final_result/confusion_compare.png  (and .svg)

Run:
    python result/plot_confusion_compare.py
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
CLF_FILE = RESULT_DIR / "clf" / "nested_cv_result_cnn.json"
REG_FILE = RESULT_DIR / "reg" / "nested_cv_result_cnn_lstm_reg.json"
OUT_PATH = RESULT_DIR / "confusion_compare.png"

# Class labels = jumlah orang (7 classes -> 0..6).
CLASS_LABELS = [str(i) for i in range(7)]

CLF_CMAP = "Blues"
REG_CMAP = "Reds"

# Bigger text everywhere.
plt.rcParams.update({
    "font.size": 16,
    "axes.titlesize": 22,
    "axes.labelsize": 18,
    "xtick.labelsize": 15,
    "ytick.labelsize": 15,
    "figure.titlesize": 24,
})


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def aggregate_cm(path: Path) -> np.ndarray:
    """Sum the per-outer-fold confusion matrices into one matrix."""
    data = json.loads(path.read_text())
    cms = [
        np.asarray(f["outer_val_metrics"]["confusion_matrix"], dtype=int)
        for f in data["outer_folds"]
    ]
    return np.sum(cms, axis=0)


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
def draw_cm(ax, cm, labels, cmap, title):
    n = cm.shape[0]
    row_sums = cm.sum(axis=1, keepdims=True)
    norm = np.divide(cm, row_sums, where=row_sums != 0)  # recall per true class

    im = ax.imshow(norm, cmap=cmap, vmin=0, vmax=1, aspect="equal")

    # annotate each cell: recall (top) + raw window count (bottom); colour=recall
    thresh = 0.5
    for i in range(n):
        for j in range(n):
            color = "white" if norm[i, j] > thresh else "black"
            ax.text(
                j, i,
                f"{norm[i, j]:.2f}\n({cm[i, j]})",
                ha="center", va="center",
                color=color, fontsize=12,
            )

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Prediksi (jumlah orang)")
    ax.set_ylabel("Aktual (jumlah orang)")

    # accuracy from the aggregated matrix, folded into the title
    acc = np.trace(cm) / cm.sum()
    ax.set_title(f"{title}\nakurasi agregat = {acc:.3f}", pad=14)
    return im


def main():
    clf_cm = aggregate_cm(CLF_FILE)
    reg_cm = aggregate_cm(REG_FILE)

    fig, (ax_clf, ax_reg) = plt.subplots(1, 2, figsize=(18, 9))

    im_clf = draw_cm(
        ax_clf, clf_cm, CLASS_LABELS, CLF_CMAP,
        title="Klasifikasi — 1D CNN",
    )
    im_reg = draw_cm(
        ax_reg, reg_cm, CLASS_LABELS, REG_CMAP,
        title="Regresi — CNN-LSTM",
    )

    fig.colorbar(im_clf, ax=ax_clf, fraction=0.046, pad=0.04, label="recall")
    fig.colorbar(im_reg, ax=ax_reg, fraction=0.046, pad=0.04, label="recall")

    fig.suptitle(
        "Confusion matrix agregat (4 outer-fold) — model terbaik",
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    fig.savefig(OUT_PATH, dpi=400, bbox_inches="tight")
    fig.savefig(OUT_PATH.with_suffix(".svg"), bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")
    print(f"Saved: {OUT_PATH.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
