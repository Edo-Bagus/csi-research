"""Regenerate the sensitivity heatmap in English, sized for a single IEEE column.

Reads the 1D CNN nested-CV results and aggregates the per-class sensitivity
breakdown across all four outer folds, weighting each fold by its window count.
"""

import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
RESULT = HERE.parent / "result" / "final_result" / "clf" / "nested_cv_result_cnn.json"
OUT = HERE / "sensitivity_heatmap.png"

CLASSES = ["1", "2", "3", "4", "5", "6"]
SCENARIOS = [("Duduk_Cluster", "Static"), ("Berdiri_Aktivitas", "Dynamic")]
ZONES = [("A", "A"), ("B", "B"), ("AB", "AB")]


def aggregate(folds, key, groups):
    """Window-weighted accuracy per (class, group) across outer folds."""
    totals = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for fold in folds:
        table = fold["outer_val_metrics"]["sensitivity"][key]
        for cls, per_group in table.items():
            for group in groups:
                entry = per_group.get(group, {})
                n = entry.get("n", 0)
                if n:
                    totals[cls][group][0] += entry["accuracy"] * n
                    totals[cls][group][1] += n
    return totals


def to_matrix(totals, groups):
    grid = np.full((len(CLASSES), len(groups)), np.nan)
    for i, cls in enumerate(CLASSES):
        for j, group in enumerate(groups):
            correct, n = totals[cls][group]
            if n:
                grid[i, j] = correct / n
    return grid


def draw(ax, grid, col_labels, title):
    im = ax.imshow(grid, cmap="RdYlGn", vmin=0.55, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=6.5)
    ax.set_yticks(range(len(CLASSES)))
    ax.set_yticklabels(CLASSES, fontsize=7)
    ax.set_title(title, fontsize=8, pad=4)

    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            value = grid[i, j]
            if np.isnan(value):
                ax.text(j, i, "--", ha="center", va="center", fontsize=7, color="0.4")
            else:
                ax.text(j, i, f"{value:.2f}".lstrip("0"), ha="center", va="center",
                        fontsize=7.5, fontweight="bold", color="black")
    ax.set_xticks(np.arange(-0.5, grid.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, grid.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="minor", length=0)
    return im


def main():
    data = json.loads(RESULT.read_text())
    folds = data["outer_folds"]

    scen_keys = [k for k, _ in SCENARIOS]
    zone_keys = [k for k, _ in ZONES]
    scen_grid = to_matrix(aggregate(folds, "by_class_scenario", scen_keys), scen_keys)
    zone_grid = to_matrix(aggregate(folds, "by_class_zone", zone_keys), zone_keys)

    fig, axes = plt.subplots(
        1, 2, figsize=(3.45, 1.75), dpi=400,
        gridspec_kw={"width_ratios": [2.35, 3], "wspace": 0.10},
    )
    draw(axes[0], scen_grid, [lbl for _, lbl in SCENARIOS], "(a) Activity")
    im = draw(axes[1], zone_grid, [lbl for _, lbl in ZONES], "(b) Zone")

    axes[0].set_ylabel("Occupancy class", fontsize=7.5)
    axes[1].set_yticklabels([])

    cbar = fig.colorbar(im, ax=axes, fraction=0.045, pad=0.03)
    cbar.ax.tick_params(labelsize=6)
    cbar.set_label("Accuracy", fontsize=7)

    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")

    for label, grid, groups in (("scenario", scen_grid, SCENARIOS), ("zone", zone_grid, ZONES)):
        print(f"\n{label}: " + "  ".join(lbl.replace(chr(10), ' ') for _, lbl in groups))
        for i, cls in enumerate(CLASSES):
            cells = " ".join("  --  " if np.isnan(v) else f"{v:.3f}" for v in grid[i])
            print(f"  class {cls}: {cells}")


if __name__ == "__main__":
    main()
