"""
Model stability visualization.

For every model in `final_result/clf` (classification) and `final_result/reg`
(regression) this script reads the nested-CV result JSON and draws, per model:

  * each outer-fold score as a small grey dot (the spread across folds),
  * the mean across folds as a large coloured dot,
  * a +/- 1 std error bar.

A tight cluster of grey dots with a short error bar == a stable model.

Two panels are produced:
  * left  : classification, accuracy per outer fold (higher = better)
  * right : regression, MAE per outer fold (lower = better)

Output: final_result/model_stability.png  (and .svg)

Run:
    python result/plot_model_stability.py
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
CLF_DIR = RESULT_DIR / "clf"
REG_DIR = RESULT_DIR / "reg"
OUT_PATH = RESULT_DIR / "model_stability.png"

# Pretty display name + plotting order. Files are matched by substring on the
# filename stem so the script keeps working if more models are added.
CLF_MODELS = [
    ("rf", "RF"),
    ("svm", "SVM"),
    ("xgb", "XGBoost"),
    ("cnn", "1D CNN"),
    ("cnn_lstm", "CNN-LSTM"),
    ("lstm", "LSTM"),
]
REG_MODELS = [
    ("rf", "RF"),
    ("svr", "SVR"),
    ("xgb", "XGBoost"),
    ("cnn", "1D CNN"),
    ("cnn_lstm", "CNN-LSTM"),
    ("lstm", "LSTM"),
]

CLF_COLOR = "#1f77b4"   # blue
REG_COLOR = "#d62728"   # red
POINT_COLOR = "#9e9e9e"  # grey per-fold dots

# Bigger text everywhere.
plt.rcParams.update({
    "font.size": 16,
    "axes.titlesize": 20,
    "axes.labelsize": 18,
    "xtick.labelsize": 15,
    "ytick.labelsize": 15,
    "legend.fontsize": 14,
    "figure.titlesize": 24,
})


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _assign_files(directory: Path, models: list[tuple[str, str]]):
    """Map each (key, label) to a concrete json file, longest key first."""
    used: set[Path] = set()
    out = []
    for key, label in sorted(models, key=lambda kv: len(kv[0]), reverse=True):
        f = None
        for cand in sorted(directory.glob("*.json")):
            if cand in used:
                continue
            norm = cand.stem.lower().replace("nested_cv_result_", "")
            if norm.endswith("_reg"):
                norm = norm[:-4]
            if norm == key:
                f = cand
                break
        if f is not None:
            used.add(f)
        out.append((key, label, f))
    # restore the original requested order
    order = {key: i for i, (key, _) in enumerate(models)}
    out.sort(key=lambda t: order[t[0]])
    return out


def load_clf(path: Path):
    """Return (per_fold_acc, mean, std) for a classification result file."""
    data = json.loads(path.read_text())
    folds = [f["outer_val_acc"] for f in data["outer_folds"]]
    mean = data.get("mean_outer_val_acc", float(np.mean(folds)))
    std = data.get("std_outer_val_acc", float(np.std(folds)))
    return np.array(folds), mean, std


def load_reg(path: Path):
    """Return (per_fold_mae, mean, std) for a regression result file."""
    data = json.loads(path.read_text())
    folds = [f["outer_val_metrics"]["mae"] for f in data["outer_folds"]]
    mean = data.get("mean_outer_mae", float(np.mean(folds)))
    std = data.get("std_outer_mae", float(np.std(folds)))
    return np.array(folds), mean, std


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
def draw_panel(ax, assigned, loader, color, ylabel, title):
    labels = []
    x = 0
    for key, label, path in assigned:
        if path is None:
            continue
        folds, mean, std = loader(path)
        labels.append(label)

        # per-fold grey dots, slight horizontal jitter so they don't overlap
        jitter = (np.random.RandomState(0).rand(len(folds)) - 0.5) * 0.18
        ax.scatter(
            np.full(len(folds), x) + jitter,
            folds,
            s=55,
            color=POINT_COLOR,
            alpha=0.7,
            zorder=2,
            label="per outer fold" if x == 0 else None,
        )
        # mean +/- std error bar
        ax.errorbar(
            x,
            mean,
            yerr=std,
            fmt="o",
            markersize=14,
            color=color,
            ecolor=color,
            elinewidth=2.4,
            capsize=8,
            capthick=2.4,
            zorder=3,
            label="mean ± std" if x == 0 else None,
        )
        x += 1

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.margins(x=0.08)
    ax.legend(frameon=False, loc="best")


def main():
    clf_assigned = _assign_files(CLF_DIR, CLF_MODELS)
    reg_assigned = _assign_files(REG_DIR, REG_MODELS)

    fig, (ax_clf, ax_reg) = plt.subplots(1, 2, figsize=(16, 7))

    draw_panel(
        ax_clf,
        clf_assigned,
        load_clf,
        CLF_COLOR,
        ylabel="Akurasi perouter fold",
        title="Klasifikasi",
    )
    draw_panel(
        ax_reg,
        reg_assigned,
        load_reg,
        REG_COLOR,
        ylabel="MAE perouter fold",
        title="Regresi",
    )

    fig.suptitle("Stabilitas model Nested-CV antar outer fold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))

    fig.savefig(OUT_PATH, dpi=400, bbox_inches="tight")
    fig.savefig(OUT_PATH.with_suffix(".svg"), bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")
    print(f"Saved: {OUT_PATH.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
