#!/usr/bin/env python3
"""Create nested k-fold cross-validation splits by file name.

Structure written to output_dir:
    outer_fold_1/
        val_files.txt
        train_files.txt        <- all non-val outer files (= inner train+val)
        inner_fold_1/
            train_files.txt
            val_files.txt
        inner_fold_2/
            ...
    outer_fold_2/
        ...

Rules
-----
- Outer: K folds (default 4).  Each outer val set contains >= 1 file per label.
- Inner: K-1 folds of the outer training set.  Each inner val set contains
  >= 1 file per label.
- No test set — all data participates in nested CV.
- Stratified round-robin assignment (same strategy as make_folds_by_filename.py).
- If a label has fewer files than requested folds the fold count is reduced
  automatically (a warning is printed).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


# ── shared helpers (mirrored from make_folds_by_filename.py) ──────────────────

def build_name_to_indices(names: np.ndarray) -> dict[str, np.ndarray]:
    unique_names, inverse = np.unique(names, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    sorted_inverse = inverse[order]
    boundaries = np.r_[0, np.flatnonzero(np.diff(sorted_inverse)) + 1, len(order)]
    name_to_indices: dict[str, np.ndarray] = {}
    for i, name in enumerate(unique_names):
        name_to_indices[str(name)] = order[boundaries[i]:boundaries[i + 1]]
    return name_to_indices


def build_file_labels(
    name_to_indices: dict[str, np.ndarray],
    labels: np.ndarray,
) -> dict[str, int]:
    file_labels: dict[str, int] = {}
    for name, idx in name_to_indices.items():
        values = labels[idx]
        if values.size == 0:
            raise ValueError(f"File {name} has no labels")
        label = int(values[0])
        if not np.all(values == label):
            raise ValueError(f"File {name} has mixed labels: {np.unique(values).tolist()}")
        file_labels[name] = label
    return file_labels


def group_files_by_label(file_labels: dict[str, int]) -> dict[int, list[str]]:
    groups: dict[int, list[str]] = {}
    for name, label in file_labels.items():
        groups.setdefault(label, []).append(name)
    return groups


def make_round_robin_folds(
    groups: dict[int, list[str]],
    n_splits: int,
    rng: np.random.Generator,
    shuffle: bool = True,
) -> list[list[str]]:
    """Stratified round-robin assignment; returns list of n_splits val-file lists."""
    folds: list[list[str]] = [[] for _ in range(n_splits)]
    for label in sorted(groups):
        group = list(groups[label])
        if shuffle:
            rng.shuffle(group)
        for i, name in enumerate(group):
            folds[i % n_splits].append(name)
    return folds


def effective_splits(groups: dict[int, list[str]], requested: int, context: str) -> int:
    """Return the largest split count that guarantees >= 1 file per label per fold."""
    # Each fold gets floor(label_size / n_splits) files; we need that >= 1,
    # so n_splits <= label_size for every label.
    min_files = min(len(v) for v in groups.values())
    cap = min(requested, min_files)
    if cap < requested:
        print(
            f"  [warning] {context}: reducing folds {requested} -> {cap} "
            f"(label with fewest files has {min_files})"
        )
    if cap < 2:
        raise ValueError(
            f"{context}: cannot create folds — a label has only {min_files} file(s). "
            "Add more data or reduce --outer-splits / --inner-splits."
        )
    return cap


def write_filelist(path: Path, names: list[str]) -> None:
    path.write_text("\n".join(names), encoding="utf-8")


# ── nested CV builder ─────────────────────────────────────────────────────────

def build_nested_folds(
    file_labels: dict[str, int],
    outer_splits: int,
    inner_splits: int,
    output_dir: Path,
    shuffle: bool,
    seed: int,
) -> None:
    all_groups = group_files_by_label(file_labels)
    sorted_labels = sorted(all_groups)

    # ── outer fold count ──────────────────────────────────────────────────────
    outer_n = effective_splits(all_groups, outer_splits, "outer CV")

    rng = np.random.default_rng(seed)
    outer_folds = make_round_robin_folds(all_groups, outer_n, rng, shuffle)

    print(f"\nOuter folds: {outer_n}  (labels: {sorted_labels})")
    print(f"Inner folds per outer: {inner_splits} (may be reduced per fold)\n")

    for o_idx, o_val_files in enumerate(outer_folds, start=1):
        o_train_files = [
            f for fold in outer_folds if fold is not o_val_files
            for f in fold
        ]

        outer_dir = output_dir / f"outer_fold_{o_idx}"
        outer_dir.mkdir(parents=True, exist_ok=True)

        write_filelist(outer_dir / "val_files.txt",   o_val_files)
        write_filelist(outer_dir / "train_files.txt", o_train_files)

        o_val_by_label   = {l: [] for l in sorted_labels}
        o_train_by_label = {l: [] for l in sorted_labels}
        for f in o_val_files:
            o_val_by_label[file_labels[f]].append(f)
        for f in o_train_files:
            o_train_by_label[file_labels[f]].append(f)

        val_counts   = {l: len(v) for l, v in o_val_by_label.items()}
        train_counts = {l: len(v) for l, v in o_train_by_label.items()}
        print(
            f"outer_fold_{o_idx}: "
            f"val={len(o_val_files)} files {val_counts}  "
            f"train={len(o_train_files)} files {train_counts}"
        )

        # ── inner folds on this outer's training set ──────────────────────────
        inner_groups = {l: v for l, v in o_train_by_label.items() if v}
        missing = [l for l in sorted_labels if not inner_groups.get(l)]
        if missing:
            raise ValueError(
                f"outer_fold_{o_idx}: labels {missing} have 0 training files. "
                "Increase data or reduce --outer-splits."
            )

        inner_n = effective_splits(
            inner_groups, inner_splits, f"outer_fold_{o_idx} inner CV"
        )
        inner_rng = np.random.default_rng(seed + o_idx)  # deterministic but different per outer
        inner_folds = make_round_robin_folds(inner_groups, inner_n, inner_rng, shuffle)

        for i_idx, i_val_files in enumerate(inner_folds, start=1):
            i_train_files = [
                f for fold in inner_folds if fold is not i_val_files
                for f in fold
            ]

            inner_dir = outer_dir / f"inner_fold_{i_idx}"
            inner_dir.mkdir(parents=True, exist_ok=True)

            write_filelist(inner_dir / "val_files.txt",   i_val_files)
            write_filelist(inner_dir / "train_files.txt", i_train_files)

            i_val_by_label   = {l: 0 for l in sorted_labels}
            i_train_by_label = {l: 0 for l in sorted_labels}
            for f in i_val_files:
                i_val_by_label[file_labels[f]] += 1
            for f in i_train_files:
                i_train_by_label[file_labels[f]] += 1

            print(
                f"  inner_fold_{i_idx}: "
                f"val={len(i_val_files)} {dict(i_val_by_label)}  "
                f"train={len(i_train_files)} {dict(i_train_by_label)}"
            )

        print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create nested k-fold CV splits by file name (no test set)."
    )
    parser.add_argument(
        "input_npz",
        type=Path,
        help="Path to merged dataset (.npz) with nama_file and total_orang.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("splitted_folder") / "nested_folds_by_file",
        help="Output folder for nested folds (default: splitted_folder/nested_folds_by_file)",
    )
    parser.add_argument(
        "--names-key",
        type=str,
        default="nama_file",
        help="Key for file names in the .npz (default: nama_file)",
    )
    parser.add_argument(
        "--label-key",
        type=str,
        default="total_orang",
        help="Key for labels used for stratification (default: total_orang)",
    )
    parser.add_argument(
        "--outer-splits",
        type=int,
        default=4,
        help="Number of outer folds (default: 4)",
    )
    parser.add_argument(
        "--inner-splits",
        type=int,
        default=None,
        help="Number of inner folds per outer fold (default: outer-splits - 1)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--no-shuffle",
        action="store_true",
        help="Disable shuffling before splitting",
    )

    args = parser.parse_args()

    if args.outer_splits < 2:
        raise ValueError("--outer-splits must be at least 2")

    inner_splits = args.inner_splits if args.inner_splits is not None else args.outer_splits - 1
    if inner_splits < 2:
        raise ValueError("inner splits must be at least 2 (outer-splits must be >= 3 when inner-splits is not set)")

    input_path = args.input_npz.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    with np.load(input_path) as data:
        for key in (args.names_key, args.label_key):
            if key not in data:
                raise KeyError(f"Missing key '{key}' in {input_path}")
        names  = np.asarray(data[args.names_key])
        labels = np.asarray(data[args.label_key])

    if names.ndim != 1:
        raise ValueError(f"{args.names_key} must be 1D, got shape {names.shape}")
    if labels.ndim != 1:
        raise ValueError(f"{args.label_key} must be 1D, got shape {labels.shape}")
    if len(names) != len(labels):
        raise ValueError(f"Length mismatch: {args.names_key}={len(names)}, {args.label_key}={len(labels)}")

    unique_names = np.unique(names)
    print(f"total records : {len(names)}")
    print(f"unique files  : {len(unique_names)}")
    print(f"outer splits  : {args.outer_splits}")
    print(f"inner splits  : {inner_splits}")
    print(f"shuffle       : {not args.no_shuffle}")
    print(f"seed          : {args.seed}")

    name_to_indices = build_name_to_indices(names)
    file_labels     = build_file_labels(name_to_indices, labels)

    label_dist = {}
    for label in set(file_labels.values()):
        label_dist[label] = sum(1 for l in file_labels.values() if l == label)
    print(f"files/label   : { {k: label_dist[k] for k in sorted(label_dist)} }")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    build_nested_folds(
        file_labels=file_labels,
        outer_splits=args.outer_splits,
        inner_splits=inner_splits,
        output_dir=output_dir,
        shuffle=not args.no_shuffle,
        seed=args.seed,
    )

    print(f"done -> {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
