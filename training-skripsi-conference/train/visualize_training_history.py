"""
Visualize per-epoch training history for each outer fold.

Usage:
    python train/visualize_training_history.py <path_to_result_json>
    python train/visualize_training_history.py train/clf/cnn/nested_cv_result.json
    python train/visualize_training_history.py train/reg/cnn/nested_cv_result_cnn_reg.json --save plot.png
"""

import json
import sys
import argparse
from pathlib import Path
import matplotlib.pyplot as plt


def load_result(json_path: Path) -> dict:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def plot_history(result: dict, save_path: Path | None = None) -> None:
    outer_folds = result.get("outer_folds", [])
    if not outer_folds:
        print("No outer_folds found in JSON.")
        return

    # Check if any fold has training_history
    histories = [f.get("training_history") for f in outer_folds]
    if not any(histories):
        print("No training_history found in JSON. Re-run training with the updated code first.")
        return

    first_history = next(h for h in histories if h)
    has_accuracy = "accuracy" in first_history

    n_folds = len(outer_folds)
    n_cols = 2 if has_accuracy else 1
    col_labels = ["Loss", "Accuracy"] if has_accuracy else ["Loss"]

    fig, axes = plt.subplots(
        n_folds, n_cols,
        figsize=(6 * n_cols, 3.5 * n_folds),
        squeeze=False,
    )

    task  = result.get("task", "")
    model = result.get("model", task)
    fig.suptitle(f"{model} — Training History per Outer Fold", fontsize=13, fontweight="bold")

    for row, fold_result in enumerate(outer_folds):
        fold_idx = fold_result["outer_fold"]
        history  = fold_result.get("training_history")

        if not history:
            for col in range(n_cols):
                axes[row, col].text(0.5, 0.5, "No history available",
                                    ha="center", va="center", transform=axes[row, col].transAxes)
            continue

        epochs = list(range(1, len(history["loss"]) + 1))
        n_epochs_run = len(epochs)

        # ── Loss ──────────────────────────────────────────────────────────────
        ax = axes[row, 0]
        ax.plot(epochs, history["loss"],     label="train", color="steelblue", linewidth=1.5)
        ax.plot(epochs, history["val_loss"], label="val",   color="coral",     linewidth=1.5, linestyle="--")
        ax.axvline(n_epochs_run, color="gray", linewidth=0.8, linestyle=":", label=f"stopped @ {n_epochs_run}")
        ax.set_title(f"Outer Fold {fold_idx} — Loss")
        ax.set_xlabel("Epoch")
        ax.set_ylabel("Loss")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # ── Accuracy (clf only) ────────────────────────────────────────────────
        if has_accuracy:
            ax = axes[row, 1]
            ax.plot(epochs, history["accuracy"],     label="train", color="steelblue", linewidth=1.5)
            ax.plot(epochs, history["val_accuracy"], label="val",   color="coral",     linewidth=1.5, linestyle="--")
            ax.axvline(n_epochs_run, color="gray", linewidth=0.8, linestyle=":", label=f"stopped @ {n_epochs_run}")
            ax.set_title(f"Outer Fold {fold_idx} — Accuracy")
            ax.set_xlabel("Epoch")
            ax.set_ylabel("Accuracy")
            ax.set_ylim(0, 1.05)
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"Saved → {save_path}")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot per-epoch training history from a nested CV result JSON."
    )
    parser.add_argument("json_path", type=Path, help="Path to nested_cv_result*.json")
    parser.add_argument("--save", type=Path, default=None,
                        help="Save the figure to this file (e.g. plot.png) instead of displaying it.")
    args = parser.parse_args()

    if not args.json_path.exists():
        print(f"Error: {args.json_path} not found.")
        sys.exit(1)

    result = load_result(args.json_path)
    plot_history(result, save_path=args.save)


if __name__ == "__main__":
    main()
