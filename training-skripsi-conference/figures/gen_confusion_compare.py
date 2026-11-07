"""Generate the side-by-side confusion matrix comparison figure.

Panel (a): 1D CNN, classification   -> clf/nested_cv_result_cnn.json
Panel (b): CNN-LSTM, regression     -> reg/nested_cv_result_cnn_lstm_reg.json

Each panel aggregates the per-outer-fold confusion matrices from the
nested-CV result into a single matrix over all held-out windows. Cell
color encodes per-true-class recall (row-normalized); the annotation is
the raw count.

Font sizes are set larger than the single-panel version so the text stays
readable at single-column width in the paper.
"""
import json
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(HERE, "..", "result", "final_result")

PANELS = [
    ("(a) 1D CNN, classification",
     os.path.join(RESULT_DIR, "clf", "nested_cv_result_cnn.json")),
    ("(b) CNN-LSTM, regression",
     os.path.join(RESULT_DIR, "reg", "nested_cv_result_cnn_lstm_reg.json")),
]

# Larger font sizes for readability at single-column width.
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 16,
})

CMAP = LinearSegmentedColormap.from_list("blues", ["#ffffff", "#08306b"])


def aggregate_cm(path):
    with open(path, "r", encoding="utf-8") as f:
        result = json.load(f)
    cm = None
    for fold in result["outer_folds"]:
        fold_cm = np.array(fold["outer_val_metrics"]["confusion_matrix"])
        cm = fold_cm if cm is None else cm + fold_cm
    print(f"{os.path.basename(path)}: aggregated {len(result['outer_folds'])} "
          f"folds, total windows = {cm.sum()}")
    return cm


fig, axes = plt.subplots(2, 1, figsize=(6.0, 11.0), dpi=300)

for ax, (title, path) in zip(axes, PANELS):
    cm = aggregate_cm(path)
    n = cm.shape[0]
    classes = [str(i) for i in range(n)]

    # Row-normalized values drive the color intensity (per-true-class recall).
    row_sums = cm.sum(axis=1, keepdims=True)
    cm_norm = cm / row_sums

    im = ax.imshow(cm_norm, cmap=CMAP, vmin=0.0, vmax=1.0)

    # Annotate each cell with the raw count.
    thresh = 0.5
    for i in range(n):
        for j in range(n):
            color = "white" if cm_norm[i, j] > thresh else "black"
            ax.text(j, i, f"{cm[i, j]}", ha="center", va="center",
                    color=color, fontsize=13)

    ax.set_title(title, fontsize=19, pad=12)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(classes, fontsize=15)
    ax.set_yticklabels(classes, fontsize=15)
    ax.set_xlabel("Predicted count", fontsize=17)
    ax.set_ylabel("True count", fontsize=17)

    # Minor gridlines between cells.
    ax.set_xticks(np.arange(-0.5, n, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n, 1), minor=True)
    ax.grid(which="minor", color="lightgray", linewidth=0.5)
    ax.tick_params(which="minor", length=0)

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Per-class recall", fontsize=16)
    cbar.ax.tick_params(labelsize=13)

fig.tight_layout()
out = os.path.join(HERE, "confusion_compare.png")
fig.savefig(out, bbox_inches="tight", dpi=300)
print(f"wrote {out}")
