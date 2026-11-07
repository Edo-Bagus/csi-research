"""
Nested K-Fold CV + Per-Outer Random-Search HP Tuning untuk XGBoostRegressor
Total People Counting berbasis CSI WiFi.

Flow:
  1. Load preprocess/featurized_dataset.npz  (X, y_total, file_per_window)
  2. Nested CV mengikuti splitted_folder/nested_folds_by_file/:
       Outer: 4 folds  |  Inner: 3 folds per outer
  3. Per outer fold o:
       a. Inner random search (N trials x 3 inner folds):
            Score = mean inner val MAE  (lower is better)
            Search space: n_estimators, learning_rate, max_depth,
                          subsample, colsample_bytree
       b. Retrain Pipeline: StandardScaler -> XGBRegressor with best_hp on full outer train
       c. Evaluate on outer val -> outer_mae[o], outer_rmse[o], outer_exact[o]
  4. Report mean +- std of outer val metrics
  5. Save best outer model (.joblib) + results (.joblib + .json)

Run dari direktori project root (CSI-ML/) atau dari train/reg/xgb/:
    python train/reg/xgb/train_xgb.py
    python train/reg/xgb/train_xgb.py --n-trials 20
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.metrics import confusion_matrix, f1_score, mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
from sklearn.utils.class_weight import compute_sample_weight

# ── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR     = Path(__file__).resolve().parent          # train/reg/xgb/
PROJECT_ROOT   = SCRIPT_DIR.parents[2]                    # CSI-ML/
PREPROCESS_DIR = PROJECT_ROOT / "preprocess"
if str(PREPROCESS_DIR) not in sys.path:
    sys.path.insert(0, str(PREPROCESS_DIR))
from utils import parse_file_metadata, compute_sensitivity

DEFAULT_DATASET_PATH = PROJECT_ROOT / "preprocess" / "featurized_dataset.npz"
DEFAULT_FOLDS_DIR    = PROJECT_ROOT / "splitted_folder" / "nested_folds_by_file"

# ── fixed settings ─────────────────────────────────────────────────────────────
RANDOM_STATE = 42
ALL_LABELS   = list(range(7))

# ── default hyperparameters ────────────────────────────────────────────────────
DEFAULT_HP: Dict[str, Any] = {
    "n_estimators":     300,
    "max_depth":        5,
    "learning_rate":    0.1,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
}

# ── HP search space ────────────────────────────────────────────────────────────
HP_SPACE: Dict[str, Any] = {
    "n_estimators":     ("choice",      [100, 200, 300]),
    "max_depth":        ("choice",      [3, 5, 7]),
    "learning_rate":    ("log_uniform", 1e-3, 0.3),
    "subsample":        ("uniform",     0.6, 1.0),
    "colsample_bytree": ("uniform",     0.6, 1.0),
}


# ── HP sampling ───────────────────────────────────────────────────────────────

def set_seed(seed: int) -> None:
    np.random.seed(seed)
    random.seed(seed)


def sample_hp(space: Dict[str, Any], rng: np.random.Generator) -> Dict[str, Any]:
    hp: Dict[str, Any] = {}
    for name, spec in space.items():
        kind = spec[0]
        if kind == "choice":
            hp[name] = rng.choice(spec[1]).item()
        elif kind == "uniform":
            hp[name] = float(rng.uniform(spec[1], spec[2]))
        elif kind == "log_uniform":
            hp[name] = float(np.exp(rng.uniform(np.log(spec[1]), np.log(spec[2]))))
        else:
            raise ValueError(f"Unknown HP space kind: {kind}")
    return hp


def format_hp(hp: Dict[str, Any]) -> str:
    return (
        f"n_est={hp['n_estimators']}  lr={hp['learning_rate']:.4g}  "
        f"depth={hp['max_depth']}  sub={hp['subsample']:.3f}  "
        f"col={hp['colsample_bytree']:.3f}"
    )


def hp_to_json_safe(hp: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in hp.items()}


# ── fold discovery / parsing ───────────────────────────────────────────────────

def discover_outer_fold_ids(folds_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("outer_fold_"):])
        for c in folds_dir.iterdir()
        if c.is_dir() and c.name.startswith("outer_fold_")
        and c.name[len("outer_fold_"):].isdigit()
    ]
    if not ids:
        raise RuntimeError(f"No outer_fold_<n> subdirs found in {folds_dir}")
    return sorted(ids)


def discover_inner_fold_ids(outer_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("inner_fold_"):])
        for c in outer_dir.iterdir()
        if c.is_dir() and c.name.startswith("inner_fold_")
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


# ── data splitting ─────────────────────────────────────────────────────────────

def build_split(
    X: np.ndarray,
    y: np.ndarray,
    file_per_window: np.ndarray,
    file_set: set,
    context: str,
) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.fromiter(
        (f in file_set for f in file_per_window),
        dtype=bool,
        count=len(file_per_window),
    )
    if mask.sum() == 0:
        raise RuntimeError(f"{context}: 0 windows matched — check file lists vs dataset")
    return X[mask], y[mask]


# ── pipeline ───────────────────────────────────────────────────────────────────

def make_pipeline(hp: Dict[str, Any]) -> Pipeline:
    return Pipeline([
        ("scaler", StandardScaler()),
        ("xgb",    XGBRegressor(
            n_estimators=int(hp["n_estimators"]),
            learning_rate=float(hp["learning_rate"]),
            max_depth=int(hp["max_depth"]),
            subsample=float(hp["subsample"]),
            colsample_bytree=float(hp["colsample_bytree"]),
            random_state=RANDOM_STATE,
            verbosity=0,
        )),
    ])


# ── metrics ────────────────────────────────────────────────────────────────────

def compute_metrics(y_true: np.ndarray, y_pred_raw: np.ndarray) -> Dict:
    mae        = float(mean_absolute_error(y_true, y_pred_raw))
    rmse       = float(np.sqrt(mean_squared_error(y_true, y_pred_raw)))
    r2         = float(r2_score(y_true, y_pred_raw))
    y_pred_int = np.clip(np.round(y_pred_raw), ALL_LABELS[0], ALL_LABELS[-1]).astype(int)
    y_true_int = y_true.astype(int)
    exact      = float((y_pred_int == y_true_int).mean())
    f1_mac     = float(f1_score(y_true_int, y_pred_int, average="macro", zero_division=0))
    within1    = float(np.mean(np.abs(y_pred_int - y_true_int) <= 1))
    within2    = float(np.mean(np.abs(y_pred_int - y_true_int) <= 2))
    cm         = confusion_matrix(y_true_int, y_pred_int, labels=ALL_LABELS)
    return {
        "mae":              round(mae,     6),
        "rmse":             round(rmse,    6),
        "r2":               round(r2,      6),
        "exact_accuracy":   round(exact,   6),
        "f1_macro":         round(f1_mac,  6),
        "within_1":         round(within1, 6),
        "within_2":         round(within2, 6),
        "confusion_matrix": cm.tolist(),
    }


def report_metrics(name: str, metrics: Dict) -> None:
    print(f"\n[{name}]")
    print(f"  MAE (people)   : {metrics['mae']:.4f}")
    print(f"  RMSE           : {metrics['rmse']:.4f}")
    print(f"  R2             : {metrics['r2']:.4f}")
    print(f"  exact accuracy : {metrics['exact_accuracy']:.4f}")
    print(f"  F1 macro       : {metrics['f1_macro']:.4f}")
    print(f"  within ±1      : {metrics['within_1']:.4f}")
    print(f"  within ±2      : {metrics['within_2']:.4f}")
    print(f"  Confusion matrix (rows=true, cols=pred; labels={ALL_LABELS}):")
    print(np.array(metrics['confusion_matrix']))


# ── inner random search ────────────────────────────────────────────────────────

def inner_random_search(
    X: np.ndarray,
    y: np.ndarray,
    file_per_window: np.ndarray,
    outer_dir: Path,
    n_trials: int,
    outer_idx: int,
) -> Tuple[Dict[str, Any], List[Dict]]:
    inner_fold_ids = discover_inner_fold_ids(outer_dir)
    n_inner        = len(inner_fold_ids)
    total_fits     = n_trials * n_inner

    print(f"\n  {'~'*60}")
    print(f"  Inner random search  (outer_fold_{outer_idx})")
    print(f"  trials={n_trials}  inner_folds={n_inner}  total_fits={total_fits}")
    print(f"  {'~'*60}")

    rng            = np.random.default_rng(RANDOM_STATE + outer_idx)
    trial_log: List[Dict] = []
    best_mean_rmse = np.inf
    best_hp        = DEFAULT_HP.copy()

    for trial_idx in range(1, n_trials + 1):
        hp = sample_hp(HP_SPACE, rng)
        print(f"\n    Trial {trial_idx}/{n_trials}  |  {format_hp(hp)}")

        inner_rmses: List[float] = []
        t0 = time.time()
        ok = True

        for i in inner_fold_ids:
            inner_dir   = outer_dir / f"inner_fold_{i}"
            train_files = set(parse_filelist(inner_dir / "train_files.txt"))
            val_files   = set(parse_filelist(inner_dir / "val_files.txt"))

            try:
                X_tr, y_tr = build_split(X, y, file_per_window, train_files, f"inner_{i} train")
                X_va, y_va = build_split(X, y, file_per_window, val_files,   f"inner_{i} val")
            except RuntimeError as exc:
                print(f"      [error] {exc}")
                ok = False
                break

            set_seed(RANDOM_STATE)
            model  = make_pipeline(hp)
            sw_tr  = compute_sample_weight("balanced", y_tr.astype(int))
            model.fit(X_tr, y_tr.astype(float), xgb__sample_weight=sw_tr)
            y_pred = model.predict(X_va)
            rmse   = float(np.sqrt(mean_squared_error(y_va, y_pred)))
            inner_rmses.append(rmse)
            print(f"      inner_fold_{i}: val_RMSE={rmse:.4f}")

        elapsed   = time.time() - t0
        mean_rmse = float(np.mean(inner_rmses)) if (ok and inner_rmses) else np.inf
        status    = "ok" if ok else "error"

        marker = "  *** NEW BEST ***" if mean_rmse < best_mean_rmse else ""
        print(f"    Trial {trial_idx}/{n_trials}  mean_inner_RMSE={mean_rmse:.4f}  elapsed={elapsed:.1f}s{marker}")

        trial_log.append({
            "trial":            trial_idx,
            "hp":               hp,
            "inner_fold_rmses": inner_rmses,
            "mean_inner_rmse":  mean_rmse,
            "elapsed":          elapsed,
            "status":           status,
        })

        if mean_rmse < best_mean_rmse:
            best_mean_rmse = mean_rmse
            best_hp        = hp

    print(f"\n  Inner search summary (outer_fold_{outer_idx}):")
    print(f"  {'Trial':<6} {'mean_inner_RMSE':>15}  HP")
    for r in sorted(trial_log, key=lambda d: d["mean_inner_rmse"]):
        marker = " <-- best" if r["hp"] is best_hp else ""
        print(f"  {r['trial']:<6} {r['mean_inner_rmse']:>15.4f}  {format_hp(r['hp'])}{marker}")
    print(f"  Best mean inner RMSE : {best_mean_rmse:.4f}")
    print(f"  Best HP             : {format_hp(best_hp)}")

    return best_hp, trial_log


# ── outer fold evaluation ──────────────────────────────────────────────────────

def train_and_eval_outer(
    X: np.ndarray,
    y: np.ndarray,
    file_per_window: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    outer_dir: Path,
    outer_idx: int,
    hp: Dict[str, Any],
) -> Tuple[Pipeline, Dict[str, float], np.ndarray, np.ndarray]:
    train_files = set(parse_filelist(outer_dir / "train_files.txt"))
    val_files   = set(parse_filelist(outer_dir / "val_files.txt"))

    X_tr, y_tr = build_split(X, y, file_per_window, train_files, f"outer_{outer_idx} train")
    X_va, y_va = build_split(X, y, file_per_window, val_files,   f"outer_{outer_idx} val")
    val_mask   = np.array([f in val_files for f in file_per_window])

    print(f"\n  Retraining on full outer train set  (train={len(X_tr)}, val={len(X_va)} windows)")
    print(f"  HP: {format_hp(hp)}")

    sw_tr = compute_sample_weight("balanced", y_tr.astype(int))
    t0    = time.time()
    model = make_pipeline(hp)
    model.fit(X_tr, y_tr.astype(float), xgb__sample_weight=sw_tr)
    print(f"  XGBRegressor trained in {time.time()-t0:.1f}s")

    y_pred  = model.predict(X_va)
    metrics = compute_metrics(y_va.astype(float), y_pred)
    report_metrics(f"Outer fold {outer_idx} val", metrics)

    file_va                = file_per_window[val_mask]
    metrics["sensitivity"] = compute_sensitivity(
        y_va.astype(int), y_pred, file_va, task="reg", all_labels=ALL_LABELS,
    )
    return model, metrics


# ── nested CV main loop ────────────────────────────────────────────────────────

def run_nested_cv(
    X: np.ndarray,
    y: np.ndarray,
    file_per_window: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    folds_dir: Path,
    n_trials: int,
    only_outer: Optional[int] = None,
) -> Tuple[Pipeline, List[Dict]]:
    outer_ids = discover_outer_fold_ids(folds_dir)
    if only_outer is not None:
        if only_outer not in outer_ids:
            raise ValueError(f"--outer-fold {only_outer} not found; available: {outer_ids}")
        outer_ids = [only_outer]
    n_outer   = len(outer_ids)

    sample_inner_n   = len(discover_inner_fold_ids(folds_dir / f"outer_fold_{outer_ids[0]}"))
    total_inner_fits = n_outer * n_trials * sample_inner_n
    total_fits       = total_inner_fits + n_outer

    print("\n" + "=" * 64)
    print("NESTED K-FOLD CV  —  XGBoostRegressor")
    print(f"  outer folds        : {n_outer}")
    print(f"  inner folds/outer  : {sample_inner_n}")
    print(f"  HP trials/outer    : {n_trials}")
    print(f"  inner fits         : {n_outer} x {n_trials} x {sample_inner_n} = {total_inner_fits}")
    print(f"  outer fits         : {n_outer}")
    print(f"  total training runs: {total_fits}")
    print(f"  X shape            : {X.shape}")
    print("=" * 64)

    outer_results: List[Dict]      = []
    best_outer_mae                 = np.inf
    best_model: Optional[Pipeline] = None

    for o in outer_ids:
        outer_dir = folds_dir / f"outer_fold_{o}"
        print(f"\n{'#'*64}")
        print(f"# OUTER FOLD {o}/{n_outer}")
        print(f"{'#'*64}")

        best_hp, trial_log = inner_random_search(
            X, y, file_per_window,
            outer_dir, n_trials, outer_idx=o,
        )

        print(f"\n  ----- Outer fold {o} final training -----")
        model, metrics = train_and_eval_outer(
            X, y, file_per_window, scenario_per_win, zone_per_win,
            outer_dir, o, best_hp,
        )

        outer_results.append({
            "outer_fold":        o,
            "best_hp":           best_hp,
            "inner_trial_log":   trial_log,
            "outer_val_metrics": metrics,
        })

        print(
            f"\n  >> outer_fold_{o}  "
            f"MAE={metrics['mae']:.4f}  RMSE={metrics['rmse']:.4f}  R2={metrics['r2']:.4f}  "
            f"exact={metrics['exact_accuracy']:.4f}  "
            f"F1={metrics['f1_macro']:.4f}  within±1={metrics['within_1']:.4f}  HP: {format_hp(best_hp)}"
        )

        if metrics["mae"] < best_outer_mae:
            best_outer_mae = metrics["mae"]
            best_model     = model

    # ── nested CV summary ──────────────────────────────────────────────────────
    maes    = np.asarray([r["outer_val_metrics"]["mae"]            for r in outer_results])
    rmses   = np.asarray([r["outer_val_metrics"]["rmse"]           for r in outer_results])
    r2s     = np.asarray([r["outer_val_metrics"]["r2"]             for r in outer_results])
    exacts  = np.asarray([r["outer_val_metrics"]["exact_accuracy"] for r in outer_results])
    f1s     = np.asarray([r["outer_val_metrics"]["f1_macro"]       for r in outer_results])
    within1 = np.asarray([r["outer_val_metrics"]["within_1"]       for r in outer_results])

    print(f"\n{'='*64}")
    print("NESTED CV SUMMARY")
    print(f"  MAE (people)   : mean={maes.mean():.4f}  std={maes.std(ddof=1):.4f}")
    print(f"  RMSE           : mean={rmses.mean():.4f}  std={rmses.std(ddof=1):.4f}")
    print(f"  R2             : mean={r2s.mean():.4f}  std={r2s.std(ddof=1):.4f}")
    print(f"  exact accuracy : mean={exacts.mean():.4f}  std={exacts.std(ddof=1):.4f}")
    print(f"  F1 macro       : mean={f1s.mean():.4f}  std={f1s.std(ddof=1):.4f}")
    print(f"  within ±1      : mean={within1.mean():.4f}  std={within1.std(ddof=1):.4f}")
    print(f"  per-fold MAEs  : {maes.round(4).tolist()}")
    for r in outer_results:
        m = r["outer_val_metrics"]
        print(
            f"  outer_fold_{r['outer_fold']}: "
            f"MAE={m['mae']:.4f}  RMSE={m['rmse']:.4f}  R2={m['r2']:.4f}  "
            f"exact={m['exact_accuracy']:.4f}  "
            f"F1={m['f1_macro']:.4f}  within±1={m['within_1']:.4f}  HP: {format_hp(r['best_hp'])}"
        )
    print(f"  best outer MAE: {best_outer_mae:.4f}")
    print("=" * 64)

    assert best_model is not None
    return best_model, outer_results


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nested K-Fold CV + Random-Search HP Tuning untuk XGBoostRegressor people counting."
    )
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET_PATH,
        help=f"Path ke featurized_dataset.npz (default: {DEFAULT_DATASET_PATH})",
    )
    parser.add_argument(
        "--folds-dir", type=Path, default=DEFAULT_FOLDS_DIR,
        help=f"Path ke nested_folds_by_file (default: {DEFAULT_FOLDS_DIR})",
    )
    parser.add_argument(
        "--n-trials", type=int, default=10,
        help="HP trials per outer fold (default: 10)",
    )
    parser.add_argument(
        "--outer-fold", type=int, default=None,
        help="Run only this outer fold index (e.g. --outer-fold 2). Omit to run all folds.",
    )
    return parser.parse_args()


def main() -> None:
    args       = parse_args()
    dataset    = args.dataset.resolve()
    folds_dir  = args.folds_dir.resolve()
    n_trials   = args.n_trials
    only_outer = args.outer_fold

    print("=" * 64)
    print("XGBoostRegressor Nested CV  —  People Counting via CSI")
    print(f"  dataset    : {dataset}")
    print(f"  folds dir  : {folds_dir}")
    print(f"  n_trials   : {n_trials}")
    print(f"  outer_fold : {only_outer if only_outer is not None else 'all'}")
    print("=" * 64)

    if not dataset.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset}")
    if not folds_dir.exists():
        raise FileNotFoundError(f"Folds dir not found: {folds_dir}")

    # ── load ──────────────────────────────────────────────────────────────────
    print("\n[1] Loading featurized_dataset.npz ...")
    data            = np.load(dataset, allow_pickle=True)
    X               = data["X"].astype(np.float32)
    y               = data["y_total"].astype(np.int32)
    file_per_window = data["file_per_window"]

    print(f"  X              : {X.shape}  {X.dtype}")
    print(f"  y_total        : {y.shape}  unique={np.unique(y).tolist()}")
    print(f"  file_per_window: {file_per_window.shape}")
    print(f"  label dist     : {dict(zip(*np.unique(y, return_counts=True)))}")

    meta_list        = [parse_file_metadata(str(f)) for f in file_per_window]
    scenario_per_win = np.array([m["scenario"] for m in meta_list], dtype=object)
    zone_per_win     = np.array([m["zone"]     for m in meta_list], dtype=object)

    # ── nested CV ─────────────────────────────────────────────────────────────
    print("\n[2] Running nested CV ...")
    best_model, outer_results = run_nested_cv(
        X, y, file_per_window, scenario_per_win, zone_per_win, folds_dir, n_trials, only_outer=only_outer
    )

    # ── save best model ───────────────────────────────────────────────────────
    best_outer    = min(outer_results, key=lambda r: r["outer_val_metrics"]["mae"])
    best_outer_id = best_outer["outer_fold"]
    model_path    = SCRIPT_DIR / "best_xgb_nested_model.joblib"
    joblib.dump(
        {
            "model":      best_model,
            "hp":         best_outer["best_hp"],
            "outer_fold": best_outer_id,
        },
        model_path,
    )
    print(f"\n  saved best model       -> {model_path}")

    # ── save joblib ───────────────────────────────────────────────────────────
    outer_maes   = [r["outer_val_metrics"]["mae"]            for r in outer_results]
    outer_rmses  = [r["outer_val_metrics"]["rmse"]           for r in outer_results]
    outer_r2s    = [r["outer_val_metrics"]["r2"]             for r in outer_results]
    outer_exacts = [r["outer_val_metrics"]["exact_accuracy"] for r in outer_results]

    joblib_path = SCRIPT_DIR / "nested_cv_result.joblib"
    joblib.dump(
        {
            "task":             "reg_xgb_nested",
            "outer_results":    outer_results,
            "outer_val_maes":   outer_maes,
            "outer_val_rmses":  outer_rmses,
            "outer_val_r2s":    outer_r2s,
            "outer_val_exacts": outer_exacts,
            "mean_outer_mae":   float(np.mean(outer_maes)),
            "mean_outer_rmse":  float(np.mean(outer_rmses)),
            "mean_outer_r2":    float(np.mean(outer_r2s)),
            "mean_outer_exact": float(np.mean(outer_exacts)),
            "best_outer_fold":  best_outer_id,
            "n_trials":         n_trials,
        },
        joblib_path,
    )
    print(f"  saved nested CV result -> {joblib_path}")

    # ── save json ─────────────────────────────────────────────────────────────
    json_payload = {
        "task":                  "reg_xgb_nested",
        "n_trials":              n_trials,
        "mean_outer_mae":        round(float(np.mean(outer_maes)),   6),
        "std_outer_mae":         round(float(np.std(outer_maes,   ddof=1)), 6),
        "mean_outer_rmse":       round(float(np.mean(outer_rmses)),  6),
        "std_outer_rmse":        round(float(np.std(outer_rmses,  ddof=1)), 6),
        "mean_outer_r2":         round(float(np.mean(outer_r2s)),   6),
        "std_outer_r2":          round(float(np.std(outer_r2s,   ddof=1)), 6),
        "mean_outer_exact":      round(float(np.mean(outer_exacts)), 6),
        "std_outer_exact":       round(float(np.std(outer_exacts, ddof=1)), 6),
        "mean_outer_f1_macro":   round(float(np.mean([r["outer_val_metrics"]["f1_macro"] for r in outer_results])), 6),
        "std_outer_f1_macro":    round(float(np.std( [r["outer_val_metrics"]["f1_macro"] for r in outer_results], ddof=1)), 6),
        "mean_outer_within1":    round(float(np.mean([r["outer_val_metrics"]["within_1"] for r in outer_results])), 6),
        "std_outer_within1":     round(float(np.std( [r["outer_val_metrics"]["within_1"] for r in outer_results], ddof=1)), 6),
        "best_outer_fold":       best_outer_id,
        "outer_folds": [
            {
                "outer_fold":        r["outer_fold"],
                "outer_val_metrics": r["outer_val_metrics"],
                "best_hp":           hp_to_json_safe(r["best_hp"]),
                "inner_trials": [
                    {
                        "trial":            t["trial"],
                        "mean_inner_rmse":  round(t["mean_inner_rmse"], 6),
                        "inner_fold_rmses": [round(m, 6) for m in t["inner_fold_rmses"]],
                        "hp":               hp_to_json_safe(t["hp"]),
                        "status":           t["status"],
                    }
                    for t in r["inner_trial_log"]
                ],
            }
            for r in outer_results
        ],
    }

    json_path = SCRIPT_DIR / "nested_cv_result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2)
    print(f"  saved nested CV JSON   -> {json_path}")

    mean_mae  = float(np.mean([r["outer_val_metrics"]["mae"]            for r in outer_results]))
    mean_rmse = float(np.mean([r["outer_val_metrics"]["rmse"]           for r in outer_results]))
    mean_r2   = float(np.mean([r["outer_val_metrics"]["r2"]             for r in outer_results]))
    mean_exact= float(np.mean([r["outer_val_metrics"]["exact_accuracy"] for r in outer_results]))
    mean_f1   = float(np.mean([r["outer_val_metrics"]["f1_macro"]       for r in outer_results]))
    mean_w1   = float(np.mean([r["outer_val_metrics"]["within_1"]       for r in outer_results]))
    print(f"\n{'='*64}")
    print(f"  mean outer — MAE={mean_mae:.4f}  RMSE={mean_rmse:.4f}  R2={mean_r2:.4f}  exact={mean_exact:.4f}  F1={mean_f1:.4f}  within±1={mean_w1:.4f}")
    print("Done.")


if __name__ == "__main__":
    main()
