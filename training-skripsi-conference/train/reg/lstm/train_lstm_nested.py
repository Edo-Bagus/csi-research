"""
Nested K-Fold CV + Per-Outer Random-Search HP Tuning untuk Pure LSTM People Counting
(regression) berbasis CSI WiFi (PyTorch + CUDA).

Flow:
  1. Load splitted_folder/nested_folds_by_file/merged.npz.
  2. Per-file preprocessing -> magnitude (242, n_time) -> windowing (50, 242).
  3. For each outer fold o (K_outer folds):
       a. Inner random search (N trials x K_inner inner folds):
            Score = mean inner val MAE  (lower is better).
       b. Retrain with best_hp on full outer train set (verbose).
       c. Evaluate on outer val set -> outer_mae[o], outer_rmse[o], outer_exact[o].
  4. Report mean ± std of outer val metrics (unbiased performance estimate).
  5. Save best outer model (.pt) + nested CV results (.joblib + .json).

Architecture (PureLSTMReg):
  Input  (batch, WINDOW_SIZE, n_subcarrier)
  LSTM1(n_subcarrier -> lstm_hidden1)           output: (batch, WINDOW_SIZE, lstm_hidden1)
  Dropout(lstm_dropout)
  LSTM2(lstm_hidden1 -> lstm_hidden2)           last hidden state: (batch, lstm_hidden2)
  Dropout(dropout)
  Linear(lstm_hidden2, 1) -> squeeze -> (batch,)

Run dari direktori train/reg/lstm/:
    python train_lstm_nested.py
    python train_lstm_nested.py --n-trials 10
    python train_lstm_nested.py --merged path/to/merged.npz --folds-dir path/to/nested_folds_by_file
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
from sklearn.utils.class_weight import compute_sample_weight

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# ── project imports ───────────────────────────────────────────────────────────
SCRIPT_DIR     = Path(__file__).resolve().parent   # train/reg/lstm/
PROJECT_ROOT   = SCRIPT_DIR.parents[2]             # CSI-ML/
PREPROCESS_DIR = PROJECT_ROOT / "preprocess"
if str(PREPROCESS_DIR) not in sys.path:
    sys.path.insert(0, str(PREPROCESS_DIR))

from utils import (
    apply_savgol_per_subcarrier,
    csi_to_mag_phase,
    impute_missing_per_subcarrier,
    window_indices,
)
from utils import config as cfg
from utils import parse_file_metadata, compute_sensitivity

# ── device ────────────────────────────────────────────────────────────────────
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ── paths ─────────────────────────────────────────────────────────────────────
DEFAULT_FOLDS_DIR   = PROJECT_ROOT / "splitted_folder" / "nested_folds_by_file"
DEFAULT_MERGED_PATH = DEFAULT_FOLDS_DIR / "merged.npz"

# ── fixed hyperparameters ─────────────────────────────────────────────────────
WINDOW_SIZE   = 100
WINDOW_STRIDE = 50
RANDOM_STATE  = cfg.RANDOM_STATE
ALL_LABELS    = list(range(7))
EPOCHS        = 100
PATIENCE      = 10

DELETE_IDX = np.asarray(cfg.DELETE_SUBCARRIER_INDICES, dtype=int)

# ── default / baseline hyperparameters ────────────────────────────────────────
DEFAULT_HP: Dict[str, Any] = {
    "lr":           1e-3,
    "weight_decay": 1e-4,
    "batch_size":   64,
    "lstm_hidden1": 125,
    "lstm_hidden2": 100,
    "lstm_dropout": 0.2,
    "dropout":      0.2,
}

# ── search space ──────────────────────────────────────────────────────────────
HP_SPACE: Dict[str, Any] = {
    "lr":           ("log_uniform", 1e-4, 1e-2),
    "weight_decay": ("log_uniform", 1e-5, 1e-2),
    "batch_size":   ("choice",      [32, 64, 128]),
    "lstm_hidden1": ("choice",      [64, 125, 256]),
    "lstm_hidden2": ("choice",      [64, 100, 128]),
    "lstm_dropout": ("uniform",     0.0, 0.5),
    "dropout":      ("uniform",     0.0, 0.75),
}


# ── model ─────────────────────────────────────────────────────────────────────

class PureLSTMReg(nn.Module):
    """Two-layer LSTM for CSI-based people counting (regression).

    Layer 1: n_subcarrier -> lstm_hidden1  (processes full sequence)
    Dropout(lstm_dropout) on output sequence
    Layer 2: lstm_hidden1 -> lstm_hidden2  (returns last hidden state)
    Dropout(dropout) -> Linear(1) -> scalar prediction
    """

    def __init__(
        self,
        n_subcarrier: int,
        lstm_hidden1: int   = DEFAULT_HP["lstm_hidden1"],
        lstm_hidden2: int   = DEFAULT_HP["lstm_hidden2"],
        lstm_dropout: float = DEFAULT_HP["lstm_dropout"],
        dropout: float      = DEFAULT_HP["dropout"],
    ):
        super().__init__()
        self.lstm1    = nn.LSTM(n_subcarrier, lstm_hidden1, num_layers=1, batch_first=True)
        self.drop_mid = nn.Dropout(lstm_dropout)
        self.lstm2    = nn.LSTM(lstm_hidden1, lstm_hidden2, num_layers=1, batch_first=True)
        self.head     = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(lstm_hidden2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, WINDOW_SIZE, n_subcarrier)
        out1, _     = self.lstm1(x)          # (batch, WINDOW_SIZE, lstm_hidden1)
        out1        = self.drop_mid(out1)
        _, (h_n, _) = self.lstm2(out1)       # h_n: (1, batch, lstm_hidden2)
        return self.head(h_n.squeeze(0)).squeeze(1)  # (batch,)


# ── helpers ───────────────────────────────────────────────────────────────────

def discover_outer_fold_ids(folds_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("outer_fold_"):])
        for c in folds_dir.iterdir()
        if c.is_dir() and c.name.startswith("outer_fold_") and c.name[len("outer_fold_"):].isdigit()
    ]
    if not ids:
        raise RuntimeError(f"No outer_fold_<n> subdirs found in {folds_dir}")
    return sorted(ids)


def discover_inner_fold_ids(outer_dir: Path) -> List[int]:
    ids = [
        int(c.name[len("inner_fold_"):])
        for c in outer_dir.iterdir()
        if c.is_dir() and c.name.startswith("inner_fold_") and c.name[len("inner_fold_"):].isdigit()
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


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


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
        f"lr={hp['lr']:.2e}  bs={hp['batch_size']}  "
        f"lh1={hp['lstm_hidden1']}  lh2={hp['lstm_hidden2']}  "
        f"ld={hp['lstm_dropout']:.2f}  drop={hp['dropout']:.2f}"
    )


def hp_to_json_safe(hp: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in hp.items()}


# ── preprocessing ─────────────────────────────────────────────────────────────

def preprocess_file_csi(rows: np.ndarray) -> np.ndarray:
    rows_f      = rows.astype(np.float64)
    csi_complex = (rows_f[:, 0::2] + 1j * rows_f[:, 1::2]).T
    valid_del   = DELETE_IDX[DELETE_IDX < csi_complex.shape[0]]
    csi_complex = np.delete(csi_complex, valid_del, axis=0)
    csi_complex = impute_missing_per_subcarrier(csi_complex)
    csi_complex = apply_savgol_per_subcarrier(csi_complex)
    mag, _      = csi_to_mag_phase(csi_complex)
    return mag.astype(np.float32)


def build_windows_from_merged(merged, normalize: bool = False) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    csi_all   = merged["csi"]
    nama_all  = merged["nama_file"]
    total_all = merged["total_orang"]

    unique_files = np.unique(nama_all)
    print(f"Building windows from {len(unique_files)} files (window={WINDOW_SIZE}, stride={WINDOW_STRIDE}, normalize={normalize}) ...")

    X_list: List[np.ndarray] = []
    y_list: List[float]      = []
    file_list: List[str]     = []

    t0 = time.time()
    for i, fname in enumerate(unique_files, start=1):
        mask  = nama_all == fname
        rows  = csi_all[mask]
        label = float(total_all[mask][0])

        mag      = preprocess_file_csi(rows)
        idx_list = window_indices(mag.shape[1], WINDOW_SIZE, WINDOW_STRIDE)
        if not idx_list:
            print(f"  [{i:>2}/{len(unique_files)}] {fname}: no valid windows — skip")
            continue

        for s, e in idx_list:
            win = mag[:, s:e]
            if win.shape[1] != WINDOW_SIZE:
                continue
            win = win.T  # (W, F)
            if normalize:
                mean = win.mean(axis=0, keepdims=True)
                std  = win.std(axis=0,  keepdims=True).clip(1e-8)
                win  = (win - mean) / std
            X_list.append(win.astype(np.float32))
            y_list.append(label)
            file_list.append(str(fname))

        if i % 5 == 0 or i == len(unique_files):
            print(
                f"  [{i:>2}/{len(unique_files)}] {fname} "
                f"(label={label}) packets={rows.shape[0]} "
                f"windows={len(idx_list)} | {time.time() - t0:.1f}s"
            )

    if not X_list:
        raise RuntimeError("No windows extracted — check merged.npz and window params")

    X_all        = np.stack(X_list, axis=0)
    y_all        = np.asarray(y_list, dtype=np.float32)
    file_per_win = np.asarray(file_list)
    meta_list        = [parse_file_metadata(f) for f in file_list]
    scenario_per_win = np.asarray([m["scenario"] for m in meta_list], dtype=object)
    zone_per_win     = np.asarray([m["zone"]     for m in meta_list], dtype=object)
    print(f"Total windows: {X_all.shape[0]}  shape: {X_all.shape}  elapsed: {time.time() - t0:.1f}s")
    return X_all, y_all, file_per_win, scenario_per_win, zone_per_win


# ── training primitives ───────────────────────────────────────────────────────

def make_loaders(
    X_tr: np.ndarray, y_tr: np.ndarray,
    X_va: np.ndarray, y_va: np.ndarray,
    batch_size: int,
    sw_tr: np.ndarray,
) -> Tuple[DataLoader, DataLoader]:
    train_ds = TensorDataset(torch.from_numpy(X_tr).float(), torch.from_numpy(y_tr).float(), torch.from_numpy(sw_tr).float())
    val_ds   = TensorDataset(torch.from_numpy(X_va).float(), torch.from_numpy(y_va).float())
    return (
        DataLoader(train_ds, batch_size=batch_size, shuffle=True,  pin_memory=True),
        DataLoader(val_ds,   batch_size=batch_size, shuffle=False, pin_memory=True),
    )


def train_one_fold(
    model: PureLSTMReg,
    train_loader: DataLoader,
    val_loader: DataLoader,
    hp: Dict[str, Any],
    verbose: bool = True,
) -> Dict:
    model     = model.to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=hp["lr"], weight_decay=hp["weight_decay"])
    criterion = nn.MSELoss(reduction='none')

    history: Dict[str, List[float]] = {"loss": [], "val_loss": []}
    best_val_loss    = float("inf")
    patience_counter = 0
    best_state: Optional[Dict] = None

    for epoch in range(1, EPOCHS + 1):
        model.train()
        run_loss = run_total = 0
        for X_b, y_b, w_b in train_loader:
            X_b, y_b, w_b = X_b.to(DEVICE, non_blocking=True), y_b.to(DEVICE, non_blocking=True), w_b.to(DEVICE, non_blocking=True)
            optimizer.zero_grad()
            preds = model(X_b)
            loss  = (criterion(preds, y_b) * w_b).mean()
            loss.backward()
            optimizer.step()
            run_loss  += loss.item() * len(y_b)
            run_total += len(y_b)

        train_loss = run_loss / run_total

        model.eval()
        val_loss_sum = val_total = 0
        with torch.no_grad():
            for X_b, y_b in val_loader:
                X_b, y_b = X_b.to(DEVICE, non_blocking=True), y_b.to(DEVICE, non_blocking=True)
                preds = model(X_b)
                loss  = criterion(preds, y_b).mean()
                val_loss_sum += loss.item() * len(y_b)
                val_total    += len(y_b)

        val_loss = val_loss_sum / val_total

        history["loss"].append(train_loss)
        history["val_loss"].append(val_loss)

        if verbose:
            print(
                f"  Epoch {epoch:>3}/{EPOCHS}  "
                f"loss(MSE)={train_loss:.4f}  val_loss(MSE)={val_loss:.4f}"
            )

        if val_loss < best_val_loss:
            best_val_loss    = val_loss
            patience_counter = 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= PATIENCE:
                if verbose:
                    print(f"  EarlyStopping triggered at epoch {epoch}")
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return history


def predict_raw(model: PureLSTMReg, X: np.ndarray, batch_size: int = 512) -> np.ndarray:
    model = model.to(DEVICE)
    model.eval()
    loader = DataLoader(TensorDataset(torch.from_numpy(X).float()), batch_size=batch_size, shuffle=False, pin_memory=True)
    preds: List[np.ndarray] = []
    with torch.no_grad():
        for (X_b,) in loader:
            preds.append(model(X_b.to(DEVICE, non_blocking=True)).cpu().numpy())
    return np.concatenate(preds)


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


def build_split(
    X: np.ndarray,
    y: np.ndarray,
    file_per_win: np.ndarray,
    file_set: set,
    context: str,
) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.fromiter((f in file_set for f in file_per_win), dtype=bool, count=len(file_per_win))
    if mask.sum() == 0:
        raise RuntimeError(f"{context}: 0 windows matched — check file lists vs merged.npz")
    return X[mask], y[mask]


# ── inner random search ───────────────────────────────────────────────────────

def inner_random_search(
    X: np.ndarray,
    y: np.ndarray,
    file_per_win: np.ndarray,
    outer_dir: Path,
    n_subcarrier: int,
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

    rng           = np.random.default_rng(RANDOM_STATE + outer_idx)
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
                X_tr, y_tr = build_split(X, y, file_per_win, train_files, f"inner_fold_{i} train")
                X_va, y_va = build_split(X, y, file_per_win, val_files,   f"inner_fold_{i} val")
            except RuntimeError as exc:
                print(f"      [error] {exc}")
                ok = False
                break

            set_seed(RANDOM_STATE)
            model = PureLSTMReg(
                n_subcarrier,
                lstm_hidden1=hp["lstm_hidden1"],
                lstm_hidden2=hp["lstm_hidden2"],
                lstm_dropout=hp["lstm_dropout"],
                dropout=hp["dropout"],
            )
            sw_tr = compute_sample_weight("balanced", y_tr.astype(int))
            train_loader, val_loader = make_loaders(X_tr, y_tr, X_va, y_va, hp["batch_size"], sw_tr)
            history = train_one_fold(model, train_loader, val_loader, hp, verbose=False)
            n_ep    = len(history["loss"])

            y_pred = predict_raw(model, X_va, batch_size=hp["batch_size"])
            rmse   = float(np.sqrt(mean_squared_error(y_va, y_pred)))
            inner_rmses.append(rmse)
            print(f"      inner_fold_{i}: val_RMSE={rmse:.4f}  ({n_ep} epochs)")

        elapsed  = time.time() - t0
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


# ── outer fold evaluation ─────────────────────────────────────────────────────

def train_and_eval_outer(
    X: np.ndarray,
    y: np.ndarray,
    file_per_win: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    outer_dir: Path,
    outer_idx: int,
    hp: Dict[str, Any],
    n_subcarrier: int,
) -> Tuple[PureLSTMReg, Dict]:
    train_files = set(parse_filelist(outer_dir / "train_files.txt"))
    val_files   = set(parse_filelist(outer_dir / "val_files.txt"))

    X_tr, y_tr = build_split(X, y, file_per_win, train_files, f"outer_fold_{outer_idx} train")
    X_va, y_va = build_split(X, y, file_per_win, val_files,   f"outer_fold_{outer_idx} val")
    val_mask   = np.array([f in val_files for f in file_per_win])

    print(f"\n  Retraining on full outer train set  (train={len(X_tr)}, val={len(X_va)} windows)")
    print(f"  HP: {format_hp(hp)}")

    set_seed(RANDOM_STATE)
    model = PureLSTMReg(
        n_subcarrier,
        lstm_hidden1=hp["lstm_hidden1"],
        lstm_hidden2=hp["lstm_hidden2"],
        lstm_dropout=hp["lstm_dropout"],
        dropout=hp["dropout"],
    )
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  trainable params: {n_params:,}")

    sw_tr = compute_sample_weight("balanced", y_tr.astype(int))
    train_loader, val_loader = make_loaders(X_tr, y_tr, X_va, y_va, hp["batch_size"], sw_tr)

    t0      = time.time()
    history = train_one_fold(model, train_loader, val_loader, hp, verbose=True)
    elapsed = time.time() - t0
    print(f"  training done: {len(history['loss'])} epochs in {elapsed:.1f}s")

    y_pred  = predict_raw(model, X_va, batch_size=hp["batch_size"])
    metrics = compute_metrics(y_va, y_pred)
    report_metrics(f"Outer fold {outer_idx} val", metrics)

    file_va                = file_per_win[val_mask]
    metrics["sensitivity"] = compute_sensitivity(
        y_va.astype(int), y_pred, file_va, task="reg", all_labels=ALL_LABELS,
    )
    return model, metrics, history


# ── main nested CV loop ───────────────────────────────────────────────────────

def run_nested_cv(
    X: np.ndarray,
    y: np.ndarray,
    file_per_win: np.ndarray,
    scenario_per_win: np.ndarray,
    zone_per_win: np.ndarray,
    folds_dir: Path,
    n_trials: int,
    only_outer: Optional[int] = None,
) -> Tuple[PureLSTMReg, List[Dict]]:
    outer_ids    = discover_outer_fold_ids(folds_dir)
    if only_outer is not None:
        if only_outer not in outer_ids:
            raise ValueError(f"--outer-fold {only_outer} not found; available: {outer_ids}")
        outer_ids = [only_outer]
    n_outer      = len(outer_ids)
    n_subcarrier = X.shape[2]

    sample_inner_n   = len(discover_inner_fold_ids(folds_dir / f"outer_fold_{outer_ids[0]}"))
    total_inner_fits = n_outer * n_trials * sample_inner_n
    total_fits       = total_inner_fits + n_outer

    print("\n" + "=" * 64)
    print("NESTED K-FOLD CV  —  Pure LSTM Regression")
    print(f"  outer folds        : {n_outer}")
    print(f"  inner folds/outer  : {sample_inner_n}")
    print(f"  HP trials/outer    : {n_trials}")
    print(f"  inner fits         : {n_outer} outer x {n_trials} trials x {sample_inner_n} inner = {total_inner_fits}")
    print(f"  outer fits         : {n_outer}  (final retrain per outer fold)")
    print(f"  total training runs: {total_fits}")
    print(f"  input=({WINDOW_SIZE}, {n_subcarrier})  device={DEVICE}")
    print("=" * 64)

    outer_results: List[Dict]              = []
    best_outer_mae                         = np.inf
    best_model: Optional[PureLSTMReg]     = None

    for o in outer_ids:
        outer_dir = folds_dir / f"outer_fold_{o}"
        print(f"\n{'#'*64}")
        print(f"# OUTER FOLD {o}/{n_outer}")
        print(f"{'#'*64}")

        best_hp, trial_log = inner_random_search(
            X, y, file_per_win,
            outer_dir, n_subcarrier,
            n_trials, outer_idx=o,
        )

        print(f"\n  ----- Outer fold {o} final training -----")
        model, metrics, history = train_and_eval_outer(
            X, y, file_per_win, scenario_per_win, zone_per_win,
            outer_dir, o, best_hp, n_subcarrier,
        )

        outer_results.append({
            "outer_fold":        o,
            "best_hp":           best_hp,
            "inner_trial_log":   trial_log,
            "outer_val_metrics": metrics,
            "training_history":  history,
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


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nested K-Fold CV + Random-Search HP Tuning untuk Pure LSTM regression people counting."
    )
    parser.add_argument("--merged",     type=Path, default=DEFAULT_MERGED_PATH,
                        help=f"Path ke merged.npz (default: {DEFAULT_MERGED_PATH})")
    parser.add_argument("--folds-dir",  type=Path, default=DEFAULT_FOLDS_DIR,
                        help=f"Path ke nested_folds_by_file (default: {DEFAULT_FOLDS_DIR})")
    parser.add_argument("--n-trials",   type=int,  default=10,
                        help="HP trials per outer fold (default: 10)")
    parser.add_argument("--outer-fold", type=int,  default=None,
                        help="Run only this outer fold index. Omit to run all folds.")
    parser.add_argument("--normalize",  action="store_true", default=False,
                        help="Apply per-window per-subcarrier z-score normalization (default: off).")
    return parser.parse_args()


def main() -> None:
    args        = parse_args()
    merged_path = args.merged.resolve()
    folds_dir   = args.folds_dir.resolve()
    n_trials    = args.n_trials
    only_outer  = args.outer_fold
    normalize   = args.normalize

    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
    print("=" * 64)
    print("Pure LSTM Regression Nested CV  —  People Counting via CSI  (PyTorch)")
    print(f"  device       : {DEVICE}  ({gpu_name})")
    print(f"  torch        : {torch.__version__}  CUDA={torch.version.cuda}")
    print(f"  merged.npz   : {merged_path}")
    print(f"  folds dir    : {folds_dir}")
    print(f"  window       : size={WINDOW_SIZE}  stride={WINDOW_STRIDE}")
    print(f"  labels       : {ALL_LABELS}")
    print(f"  n_trials     : {n_trials}")
    print(f"  outer_fold   : {only_outer if only_outer is not None else 'all'}")
    print(f"  normalize    : {normalize}")
    print("=" * 64)

    if not merged_path.exists():
        raise FileNotFoundError(f"merged.npz not found: {merged_path}")

    print("\n[1] Loading merged.npz ...")
    merged = np.load(merged_path, allow_pickle=True)
    print(f"  csi         : {merged['csi'].shape}  {merged['csi'].dtype}")
    print(f"  total_orang : unique={np.unique(merged['total_orang']).tolist()}")
    print(f"  nama_file   : {merged['nama_file'].shape}")

    print("\n[2] Preprocessing & windowing ...")
    X, y, file_per_win, scenario_per_win, zone_per_win = build_windows_from_merged(merged, normalize=normalize)
    print(f"  X shape    : {X.shape}")
    print(f"  y shape    : {y.shape}")
    print(f"  label dist : {dict(zip(*np.unique(y, return_counts=True)))}")

    print("\n[3] Running nested CV ...")
    best_model, outer_results = run_nested_cv(
        X, y, file_per_win, scenario_per_win, zone_per_win, folds_dir, n_trials, only_outer=only_outer
    )

    # ── save model ────────────────────────────────────────────────────────────
    best_outer = min(outer_results, key=lambda r: r["outer_val_metrics"]["mae"])
    model_path = SCRIPT_DIR / "best_lstm_reg_nested_model.pt"
    torch.save(
        {
            "model_state_dict": best_model.cpu().state_dict(),
            "n_subcarrier":     X.shape[2],
            "window_size":      WINDOW_SIZE,
            "hp":               best_outer["best_hp"],
        },
        model_path,
    )
    print(f"\n  saved best model      -> {model_path}")

    # ── save joblib ───────────────────────────────────────────────────────────
    outer_maes   = [r["outer_val_metrics"]["mae"]            for r in outer_results]
    outer_rmses  = [r["outer_val_metrics"]["rmse"]           for r in outer_results]
    outer_r2s    = [r["outer_val_metrics"]["r2"]             for r in outer_results]
    outer_exacts = [r["outer_val_metrics"]["exact_accuracy"] for r in outer_results]

    joblib_path = SCRIPT_DIR / "nested_cv_result_lstm_reg.joblib"
    joblib.dump(
        {
            "task":             "reg_lstm_nested",
            "outer_results":    outer_results,
            "outer_val_maes":   outer_maes,
            "outer_val_rmses":  outer_rmses,
            "outer_val_r2s":    outer_r2s,
            "outer_val_exacts": outer_exacts,
            "mean_outer_mae":   float(np.mean(outer_maes)),
            "mean_outer_rmse":  float(np.mean(outer_rmses)),
            "mean_outer_r2":    float(np.mean(outer_r2s)),
            "mean_outer_exact": float(np.mean(outer_exacts)),
            "best_outer_fold":  best_outer["outer_fold"],
            "window_size":      WINDOW_SIZE,
            "window_stride":    WINDOW_STRIDE,
            "normalize":        normalize,
            "n_trials":         n_trials,
        },
        joblib_path,
    )
    print(f"  saved nested CV result -> {joblib_path}")

    # ── save json ─────────────────────────────────────────────────────────────
    json_payload = {
        "task":                  "reg_lstm_nested",
        "model":                 "pure_lstm_reg",
        "window_size":           WINDOW_SIZE,
        "window_stride":         WINDOW_STRIDE,
        "normalize":             normalize,
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
        "best_outer_fold":       best_outer["outer_fold"],
        "outer_folds": [
            {
                "outer_fold":        r["outer_fold"],
                "outer_val_metrics": r["outer_val_metrics"],
                "best_hp":           hp_to_json_safe(r["best_hp"]),
                "training_history": {
                    key: [round(v, 6) for v in vals]
                    for key, vals in r["training_history"].items()
                },
                "inner_trials": [
                    {
                        "trial":           t["trial"],
                        "mean_inner_rmse":  round(t["mean_inner_rmse"], 6),
                        "inner_fold_rmses": [round(m, 6) for m in t["inner_fold_rmses"]],
                        "hp":              hp_to_json_safe(t["hp"]),
                        "status":          t["status"],
                    }
                    for t in r["inner_trial_log"]
                ],
            }
            for r in outer_results
        ],
    }
    json_path = SCRIPT_DIR / "nested_cv_result_lstm_reg.json"
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
