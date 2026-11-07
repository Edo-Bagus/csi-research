"""
Nested K-Fold CV + Per-Outer Random-Search HP Tuning untuk XGBoost People Counting
(classification only) berbasis CSI WiFi.

Flow:
  1. Load preprocess/featurized_dataset.npz (X, y_total, file_per_window).
  2. For each outer fold o (K_outer folds in nested_folds_by_file/outer_fold_<n>):
       a. Inner random search (N trials x K_inner inner folds):
            Score = mean inner val accuracy.
       b. Retrain with best_hp on full outer train set.
       c. Evaluate on outer val set -> outer_acc[o].
  3. Report mean ± std of outer val accuracies (unbiased performance estimate).
  4. Save best outer model (.joblib) + nested CV results (.joblib + .json).

Run dari direktori CSI-ML/:
    python train/clf/xgb/train_final_xgb.py
    python train/clf/xgb/train_final_xgb.py --n-trials 10
    python train/clf/xgb/train_final_xgb.py --featurized path/to/featurized_dataset.npz
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

PROJECT_ROOT   = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCRIPT_DIR     = Path(__file__).resolve().parent
PREPROCESS_DIR = PROJECT_ROOT / "preprocess"
if str(PREPROCESS_DIR) not in sys.path:
    sys.path.insert(0, str(PREPROCESS_DIR))
from utils import parse_file_metadata, compute_sensitivity

DEFAULT_FOLDS_DIR    = PROJECT_ROOT / "splitted_folder" / "nested_folds_by_file"
DEFAULT_DATASET_PATH = PROJECT_ROOT / "preprocess" / "featurized_dataset.npz"

ALL_LABELS   = list(range(7))
RANDOM_STATE = 42

# ── HP search space ───────────────────────────────────────────────────────────
HP_SPACE: Dict[str, Any] = {
    "n_estimators":    ("choice",      [100, 200, 300]),
    "max_depth":       ("choice",      [3, 5, 7]),
    "learning_rate":   ("log_uniform", 1e-3, 0.3),
    "subsample":       ("uniform",     0.6, 1.0),
    "colsample_bytree": ("uniform",    0.6, 1.0),
}

DEFAULT_HP: Dict[str, Any] = {
    "n_estimators":    300,
    "max_depth":       5,
    "learning_rate":   0.1,
    "subsample":       0.8,
    "colsample_bytree": 0.8,
}


# ── fold discovery ────────────────────────────────────────────────────────────

def discover_outer_fold_ids(folds_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("outer_fold_"):])
        for c in folds_dir.iterdir()
        if c.is_dir()
        and c.name.startswith("outer_fold_")
        and c.name[len("outer_fold_"):].isdigit()
    ]
    if not ids:
        raise RuntimeError(f"No outer_fold_<n> subdirs found in {folds_dir}")
    return sorted(ids)


def discover_inner_fold_ids(outer_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("inner_fold_"):])
        for c in outer_dir.iterdir()
        if c.is_dir()
        and c.name.startswith("inner_fold_")
        and c.name[len("inner_fold_"):].isdigit()
    ]
    if not ids:
        raise RuntimeError(f"No inner_fold_<n> subdirs found in {outer_dir}")
    return sorted(ids)


def parse_filelist(path: Path) -> List[str]:
    files: List[str] = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            fname = line.partition("\t")[2].strip() if "\t" in line else line.strip()
            if fname:
                files.append(fname)
    return files


# ── helpers ───────────────────────────────────────────────────────────────────

def set_seed(seed: int) -> None:
    np.random.seed(seed)
    random.seed(seed)


def sample_hp(space: Dict[str, Any], rng: np.random.Generator) -> Dict[str, Any]:
    hp: Dict[str, Any] = {}
    for name, spec in space.items():
        kind = spec[0]
        if kind == "choice":
            hp[name] = spec[1][int(rng.choice(len(spec[1])))]
        elif kind == "uniform":
            hp[name] = float(rng.uniform(spec[1], spec[2]))
        elif kind == "log_uniform":
            hp[name] = float(np.exp(rng.uniform(np.log(spec[1]), np.log(spec[2]))))
        else:
            raise ValueError(f"Unknown HP space kind: {kind}")
    return hp


def format_hp(hp: Dict[str, Any]) -> str:
    return (
        f"n_est={hp['n_estimators']}  depth={hp['max_depth']}  "
        f"lr={hp['learning_rate']:.4f}  sub={hp['subsample']:.2f}  "
        f"col={hp['colsample_bytree']:.2f}"
    )


def hp_to_json_safe(hp: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in hp.items()}


def build_xgb_classifier(hp: Dict[str, Any], n_classes: int) -> XGBClassifier:
    return XGBClassifier(
        objective="multi:softprob",
        num_class=n_classes,
        n_estimators=hp["n_estimators"],
        max_depth=hp["max_depth"],
        learning_rate=hp["learning_rate"],
        subsample=hp["subsample"],
        colsample_bytree=hp["colsample_bytree"],
        tree_method="hist",
        n_jobs=-1,
        eval_metric="mlogloss",
        random_state=RANDOM_STATE,
        verbosity=0,
    )


def build_split(
    X: np.ndarray,
    y_enc: np.ndarray,
    file_per_win: np.ndarray,
    file_set: set,
    context: str,
) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.fromiter((f in file_set for f in file_per_win), dtype=bool, count=len(file_per_win))
    if mask.sum() == 0:
        raise RuntimeError(f"{context}: 0 windows matched — check file lists vs featurized_dataset.npz")
    return X[mask], y_enc[mask]


def report_classification(name: str, y_true: np.ndarray, y_pred: np.ndarray) -> Dict:
    exact_acc = accuracy_score(y_true, y_pred)
    f1_mac    = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    within1   = float(np.mean(np.abs(y_pred - y_true) <= 1))
    within2   = float(np.mean(np.abs(y_pred - y_true) <= 2))
    mae       = float(np.mean(np.abs(y_pred - y_true)))

    print(f"\n[{name}]")
    print(f"  exact accuracy : {exact_acc:.4f}")
    print(f"  F1 macro       : {f1_mac:.4f}")
    print(f"  within ±1      : {within1:.4f}")
    print(f"  within ±2      : {within2:.4f}")
    print(f"  MAE (people)   : {mae:.4f}")
    print(classification_report(y_true, y_pred, labels=ALL_LABELS, zero_division=0))
    cm = confusion_matrix(y_true, y_pred, labels=ALL_LABELS)
    print(f"Confusion matrix (rows=true, cols=pred; labels={ALL_LABELS}):")
    print(cm)

    return {
        "exact_accuracy":   round(exact_acc, 6),
        "f1_macro":         round(f1_mac,    6),
        "within_1":         round(within1,   6),
        "within_2":         round(within2,   6),
        "mae":              round(mae,        6),
        "confusion_matrix": cm.tolist(),
    }


# ── inner random search ───────────────────────────────────────────────────────

def inner_random_search(
    X: np.ndarray,
    y_enc: np.ndarray,
    file_per_win: np.ndarray,
    outer_dir: Path,
    n_classes: int,
    n_trials: int,
    outer_idx: int,
) -> Tuple[Dict[str, Any], List[Dict]]:
    inner_fold_ids = discover_inner_fold_ids(outer_dir)
    n_inner        = len(inner_fold_ids)
    total_fits     = n_trials * n_inner

    print(f"\n  {'~'*56}")
    print(f"  Inner random search  (outer_fold_{outer_idx})")
    print(f"  trials={n_trials}  inner_folds={n_inner}  total_fits={n_trials} x {n_inner} = {total_fits}")
    print(f"  {'~'*56}")

    rng        = np.random.default_rng(RANDOM_STATE + outer_idx)
    trial_log: List[Dict] = []
    best_mean  = -np.inf
    best_hp    = DEFAULT_HP.copy()

    for trial_idx in range(1, n_trials + 1):
        hp = sample_hp(HP_SPACE, rng)
        print(f"\n    Trial {trial_idx}/{n_trials}  |  {format_hp(hp)}")

        inner_accs: List[float] = []
        t0 = time.time()
        ok = True

        for i in inner_fold_ids:
            inner_dir   = outer_dir / f"inner_fold_{i}"
            train_files = set(parse_filelist(inner_dir / "train_files.txt"))
            val_files   = set(parse_filelist(inner_dir / "val_files.txt"))

            try:
                X_tr, y_tr = build_split(X, y_enc, file_per_win, train_files, f"inner_fold_{i} train")
                X_va, y_va = build_split(X, y_enc, file_per_win, val_files,   f"inner_fold_{i} val")
            except RuntimeError as exc:
                print(f"      [error] {exc}")
                ok = False
                break

            set_seed(RANDOM_STATE)
            model = build_xgb_classifier(hp, n_classes)
            model.fit(X_tr, y_tr, sample_weight=compute_sample_weight("balanced", y_tr))
            y_pred = model.predict(X_va)
            acc    = float(accuracy_score(y_va, y_pred))
            inner_accs.append(acc)
            print(f"      inner_fold_{i}: val_acc={acc:.4f}")

        elapsed  = time.time() - t0
        mean_acc = float(np.mean(inner_accs)) if (ok and inner_accs) else 0.0
        status   = "ok" if ok else "error"

        marker = "  *** NEW BEST ***" if mean_acc > best_mean else ""
        print(f"    Trial {trial_idx}/{n_trials} done  mean_inner_acc={mean_acc:.4f}  elapsed={elapsed:.1f}s{marker}")

        trial_log.append({
            "trial":           trial_idx,
            "hp":              hp,
            "inner_fold_accs": inner_accs,
            "mean_inner_acc":  mean_acc,
            "elapsed":         elapsed,
            "status":          status,
        })

        if mean_acc > best_mean:
            best_mean = mean_acc
            best_hp   = hp

    print(f"\n  Inner search summary (outer_fold_{outer_idx}):")
    print(f"  {'Trial':<6} {'mean_inner_acc':>14}  HP")
    for r in sorted(trial_log, key=lambda d: d["mean_inner_acc"], reverse=True):
        marker = " <-- best" if r["hp"] is best_hp else ""
        print(f"  {r['trial']:<6} {r['mean_inner_acc']:>14.4f}  {format_hp(r['hp'])}{marker}")
    print(f"  Best mean inner acc : {best_mean:.4f}")
    print(f"  Best HP             : {format_hp(best_hp)}")

    return best_hp, trial_log


# ── outer fold evaluation ─────────────────────────────────────────────────────

def train_and_eval_outer(
    X: np.ndarray,
    y_enc: np.ndarray,
    file_per_win: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    label_encoder: LabelEncoder,
    outer_dir: Path,
    outer_idx: int,
    hp: Dict[str, Any],
    n_classes: int,
) -> Tuple[XGBClassifier, Dict]:
    train_files = set(parse_filelist(outer_dir / "train_files.txt"))
    val_files   = set(parse_filelist(outer_dir / "val_files.txt"))

    X_tr, y_tr = build_split(X, y_enc, file_per_win, train_files, f"outer_fold_{outer_idx} train")
    X_va, y_va = build_split(X, y_enc, file_per_win, val_files,   f"outer_fold_{outer_idx} val")
    val_mask   = np.array([f in val_files for f in file_per_win])

    print(f"\n  Retraining on full outer train set  (train={len(X_tr)}, val={len(X_va)} windows)")
    print(f"  HP: {format_hp(hp)}")

    set_seed(RANDOM_STATE)
    model = build_xgb_classifier(hp, n_classes)
    t0    = time.time()
    model.fit(X_tr, y_tr, sample_weight=compute_sample_weight("balanced", y_tr))
    print(f"  fit done in {time.time() - t0:.1f}s")

    y_pred_enc  = model.predict(X_va)
    y_va_orig   = label_encoder.inverse_transform(y_va)
    y_pred_orig = label_encoder.inverse_transform(y_pred_enc)
    metrics = report_classification(f"Outer fold {outer_idx} val", y_va_orig, y_pred_orig)

    file_va                = file_per_win[val_mask]
    metrics["sensitivity"] = compute_sensitivity(
        y_va_orig, y_pred_orig, file_va, task="clf", all_labels=ALL_LABELS,
    )
    return model, metrics


# ── main nested CV loop ───────────────────────────────────────────────────────

def run_nested_cv(
    X: np.ndarray,
    y: np.ndarray,
    file_per_win: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    label_encoder: LabelEncoder,
    folds_dir: Path,
    n_trials: int,
    only_outer: int | None = None,
) -> Tuple[XGBClassifier, List[Dict]]:
    outer_ids = discover_outer_fold_ids(folds_dir)
    if only_outer is not None:
        if only_outer not in outer_ids:
            raise ValueError(f"--outer-fold {only_outer} not found; available: {outer_ids}")
        outer_ids = [only_outer]
    n_outer   = len(outer_ids)
    n_classes = len(label_encoder.classes_)
    y_enc     = label_encoder.transform(y).astype(np.int32)

    sample_inner_n   = len(discover_inner_fold_ids(folds_dir / f"outer_fold_{outer_ids[0]}"))
    total_inner_fits = n_outer * n_trials * sample_inner_n

    print("\n" + "=" * 64)
    print("NESTED K-FOLD CV  —  XGBoost Classifier")
    print(f"  outer folds        : {n_outer}")
    print(f"  inner folds/outer  : {sample_inner_n}")
    print(f"  HP trials/outer    : {n_trials}")
    print(f"  inner fits         : {n_outer} x {n_trials} x {sample_inner_n} = {total_inner_fits}")
    print(f"  outer fits         : {n_outer}  (final retrain per outer fold)")
    print(f"  classes            : {n_classes}  labels={label_encoder.classes_.tolist()}")
    print(f"  feature dim        : {X.shape[1]}")
    print("=" * 64)

    outer_results: List[Dict] = []
    best_outer_acc = -np.inf
    best_model: XGBClassifier | None = None

    for o in outer_ids:
        outer_dir = folds_dir / f"outer_fold_{o}"
        print(f"\n{'#'*64}")
        print(f"# OUTER FOLD {o}/{n_outer}")
        print(f"{'#'*64}")

        best_hp, trial_log = inner_random_search(
            X, y_enc, file_per_win,
            outer_dir, n_classes, n_trials, outer_idx=o,
        )

        print(f"\n  ----- Outer fold {o} final training -----")
        model, outer_metrics = train_and_eval_outer(
            X, y_enc, file_per_win, scenario_per_win, zone_per_win,
            label_encoder, outer_dir, o, best_hp, n_classes,
        )
        outer_acc = outer_metrics["exact_accuracy"]

        outer_results.append({
            "outer_fold":       o,
            "best_hp":          best_hp,
            "inner_trial_log":  trial_log,
            "outer_val_acc":    outer_acc,
            "outer_val_metrics": outer_metrics,
        })

        print(f"\n  >> outer_fold_{o} val_acc={outer_acc:.4f}  F1={outer_metrics['f1_macro']:.4f}  within±1={outer_metrics['within_1']:.4f}  MAE={outer_metrics['mae']:.4f}  HP: {format_hp(best_hp)}")

        if outer_acc > best_outer_acc:
            best_outer_acc = outer_acc
            best_model     = model

    accs    = np.asarray([r["outer_val_acc"]                    for r in outer_results])
    f1s     = np.asarray([r["outer_val_metrics"]["f1_macro"]    for r in outer_results])
    maes    = np.asarray([r["outer_val_metrics"]["mae"]         for r in outer_results])
    within1 = np.asarray([r["outer_val_metrics"]["within_1"]   for r in outer_results])
    print(f"\n{'='*64}")
    print("NESTED CV SUMMARY")
    print(f"  exact accuracy : mean={accs.mean():.4f}  std={accs.std(ddof=1):.4f}")
    print(f"  F1 macro       : mean={f1s.mean():.4f}  std={f1s.std(ddof=1):.4f}")
    print(f"  within ±1      : mean={within1.mean():.4f}  std={within1.std(ddof=1):.4f}")
    print(f"  MAE (people)   : mean={maes.mean():.4f}  std={maes.std(ddof=1):.4f}")
    print(f"  per-fold accs  : {accs.round(4).tolist()}")
    for r in outer_results:
        m = r["outer_val_metrics"]
        print(f"  outer_fold_{r['outer_fold']}: acc={m['exact_accuracy']:.4f}  F1={m['f1_macro']:.4f}  within±1={m['within_1']:.4f}  MAE={m['mae']:.4f}  HP: {format_hp(r['best_hp'])}")
    print(f"  best outer fold acc: {best_outer_acc:.4f}")
    print("=" * 64)

    assert best_model is not None
    return best_model, outer_results


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nested K-Fold CV + Random-Search HP Tuning untuk XGBoost people counting."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH,
                        help=f"Path ke featurized_dataset.npz (default: {DEFAULT_DATASET_PATH})")
    parser.add_argument("--folds-dir",  type=Path, default=DEFAULT_FOLDS_DIR,
                        help=f"Path ke nested_folds_by_file (default: {DEFAULT_FOLDS_DIR})")
    parser.add_argument("--n-trials",   type=int,  default=10,
                        help="HP trials per outer fold (default: 10)")
    parser.add_argument("--outer-fold", type=int, default=None,
                        help="Run only this outer fold index (e.g. --outer-fold 2). Omit to run all folds.")
    return parser.parse_args()


def main() -> None:
    args            = parse_args()
    dataset_path = args.dataset.resolve()
    folds_dir    = args.folds_dir.resolve()
    n_trials     = args.n_trials
    only_outer   = args.outer_fold

    print("=" * 64)
    print("XGBoost Nested CV  —  People Counting via CSI")
    print(f"  dataset    : {dataset_path}")
    print(f"  folds dir  : {folds_dir}")
    print(f"  labels     : {ALL_LABELS}")
    print(f"  n_trials   : {n_trials}")
    print(f"  outer_fold : {only_outer if only_outer is not None else 'all'}")
    print("=" * 64)

    if not dataset_path.exists():
        raise FileNotFoundError(f"featurized_dataset.npz not found: {dataset_path}")

    print("\n[1] Loading featurized_dataset.npz ...")
    feat = np.load(dataset_path, allow_pickle=False)
    X            = feat["X"]
    y_total      = feat["y_total"]
    file_per_win = feat["file_per_window"]
    print(f"  X              : {X.shape}  {X.dtype}")
    print(f"  y_total        : {y_total.shape}  unique={np.unique(y_total).tolist()}")
    print(f"  file_per_window: {file_per_win.shape}")
    print(f"  label dist     : {dict(zip(*np.unique(y_total, return_counts=True)))}")

    meta_list        = [parse_file_metadata(str(f)) for f in file_per_win]
    scenario_per_win = np.array([m["scenario"] for m in meta_list], dtype=object)
    zone_per_win     = np.array([m["zone"]     for m in meta_list], dtype=object)

    label_encoder = LabelEncoder()
    label_encoder.fit(y_total)
    print(f"  LabelEncoder   : {label_encoder.classes_.tolist()} -> 0..{len(label_encoder.classes_)-1}")

    print("\n[2] Running nested CV ...")
    best_model, outer_results = run_nested_cv(
        X, y_total, file_per_win, scenario_per_win, zone_per_win,
        label_encoder, folds_dir, n_trials, only_outer=only_outer
    )

    # ── save best model ───────────────────────────────────────────────────────
    model_path = SCRIPT_DIR / "best_xgb_nested_model.joblib"
    joblib.dump(
        {
            "model":         best_model,
            "label_encoder": label_encoder,
        },
        model_path,
    )
    print(f"\n  saved best model       -> {model_path}")

    # ── save joblib ───────────────────────────────────────────────────────────
    outer_val_accs = [r["outer_val_acc"] for r in outer_results]
    joblib_path = SCRIPT_DIR / "nested_cv_result_clf.joblib"
    joblib.dump(
        {
            "task":            "clf_nested",
            "outer_results":   outer_results,
            "outer_val_accs":  outer_val_accs,
            "mean_outer_acc":  float(np.mean(outer_val_accs)),
            "std_outer_acc":   float(np.std(outer_val_accs, ddof=1)),
            "label_encoder":   label_encoder,
            "n_trials":        n_trials,
        },
        joblib_path,
    )
    print(f"  saved nested CV result -> {joblib_path}")

    # ── save json ─────────────────────────────────────────────────────────────
    json_payload = {
        "task":                 "clf_nested",
        "n_trials":             n_trials,
        "mean_outer_val_acc":   round(float(np.mean(outer_val_accs)), 6),
        "std_outer_val_acc":    round(float(np.std(outer_val_accs, ddof=1)), 6),
        "mean_outer_f1_macro":  round(float(np.mean([r["outer_val_metrics"]["f1_macro"] for r in outer_results])), 6),
        "std_outer_f1_macro":   round(float(np.std( [r["outer_val_metrics"]["f1_macro"] for r in outer_results], ddof=1)), 6),
        "outer_folds": [
            {
                "outer_fold":        r["outer_fold"],
                "outer_val_acc":     round(r["outer_val_acc"], 6),
                "outer_val_metrics": r["outer_val_metrics"],
                "best_hp":           hp_to_json_safe(r["best_hp"]),
                "inner_trials": [
                    {
                        "trial":           t["trial"],
                        "mean_inner_acc":  round(t["mean_inner_acc"], 6),
                        "inner_fold_accs": [round(a, 6) for a in t["inner_fold_accs"]],
                        "hp":              hp_to_json_safe(t["hp"]),
                        "status":          t["status"],
                    }
                    for t in r["inner_trial_log"]
                ],
            }
            for r in outer_results
        ],
    }
    json_path = SCRIPT_DIR / "nested_cv_result_clf.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)
    print(f"  saved nested CV JSON   -> {json_path}")

    mean_acc = float(np.mean([r["outer_val_acc"]                  for r in outer_results]))
    mean_f1  = float(np.mean([r["outer_val_metrics"]["f1_macro"]  for r in outer_results]))
    mean_w1  = float(np.mean([r["outer_val_metrics"]["within_1"]  for r in outer_results]))
    mean_mae = float(np.mean([r["outer_val_metrics"]["mae"]       for r in outer_results]))
    print(f"\n{'='*64}")
    print(f"  mean outer — exact={mean_acc:.4f}  F1={mean_f1:.4f}  within±1={mean_w1:.4f}  MAE={mean_mae:.4f}")
    print("Done.")


if __name__ == "__main__":
    main()
