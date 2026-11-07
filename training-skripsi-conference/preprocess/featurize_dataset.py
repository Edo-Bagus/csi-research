"""
Featurize merged.npz -> preprocessed dataset (X, y_total, file_per_window).

Flow:
  1. Load merged.npz
  2. Per file: reconstruct complex CSI (256, n_time)
     -> delete control subcarriers (256 -> 242)
  3. Preprocessing: impute -> Savitzky-Golay -> csi_to_mag_phase
  4. Windowing 50/25 + extract_features_from_window per window:
       features='mag'  : 242 * 7  = 1694-dim  (stats + fft_energy + mad)
       features='both' : 242 * 13 = 3146-dim  (mag stats + fft_energy + mag_mad
                                                + phase stats + phase_mad)
  5. Save (X, y_total, file_per_window) to `featurized_dataset.npz`

Run dari direktori `ml/`:
    python /featurize_dataset.py
    python /featurize_dataset.py --output path/to/output.npz
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from utils import (
    apply_savgol_per_subcarrier,
    csi_to_mag_phase,
    extract_features_from_window,
    hampel_filter_per_subcarrier,
    impute_missing_per_subcarrier,
    window_indices,
)
from utils import config

WINDOW_SIZE = 100
WINDOW_STRIDE = 50
DATA_DIR = Path(__file__).resolve().parent
MERGED_PATH = DATA_DIR / "merged.npz"
DELETE_SUBCARRIER_INDICES = np.asarray(config.DELETE_SUBCARRIER_INDICES, dtype=int)


def featurize_all_files(
    merged,
    features: str = "both",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Featurize semua file sekali (one-pass). Return (X, y_total, file_per_window).

    Parameters
    ----------
    features : {'mag', 'phase', 'both'}
        Which components to include in the feature vector.
    """
    csi_all = merged["csi"]
    nama_all = merged["nama_file"]
    total_all = merged["total_orang"]

    unique_files = np.unique(nama_all)
    print(f"Featurize {len(unique_files)} files (window={WINDOW_SIZE}/{WINDOW_STRIDE}, features={features})")

    X_list: List[np.ndarray] = []
    yt_list: List[int] = []
    file_list: List[str] = []

    t0 = time.time()
    for i, fname in enumerate(unique_files, start=1):
        mask = nama_all == fname
        rows = csi_all[mask]  # (n_packet, 512) int16

        total_vals = total_all[mask]
        assert np.all(total_vals == total_vals[0]), f"total_orang tidak konstan di {fname}"
        total_label = int(total_vals[0])

        rows_f = rows.astype(np.float64)
        csi_complex = (rows_f[:, 0::2] + 1j * rows_f[:, 1::2]).T  # (256, n_time)

        valid_del = DELETE_SUBCARRIER_INDICES[
            DELETE_SUBCARRIER_INDICES < csi_complex.shape[0]
        ]
        csi_complex = np.delete(csi_complex, valid_del, axis=0)  # (242, n_time)

        csi_complex = impute_missing_per_subcarrier(csi_complex)
        csi_complex = apply_savgol_per_subcarrier(csi_complex)
        csi_complex = hampel_filter_per_subcarrier(csi_complex)    # suppress spike packets before phase extraction
        mag, phase  = csi_to_mag_phase(csi_complex)
        mag         = mag[:, 1:]                                    # align time axis: np.diff shrinks phase to n_time-1
        phase       = np.clip(phase, -np.pi, np.pi)                 # clip residual hardware-reset spikes

        idx_list = window_indices(mag.shape[1], WINDOW_SIZE, WINDOW_STRIDE)
        if not idx_list:
            print(
                f"  [{i:>2}/{len(unique_files)}] {fname}: no windows "
                f"(n_time={mag.shape[1]}) — skip"
            )
            continue

        for s, e in idx_list:
            if features == "mag":
                feat = extract_features_from_window(mag[:, s:e], None)
            elif features == "phase":
                feat = extract_features_from_window(phase[:, s:e], None)
            else:
                feat = extract_features_from_window(mag[:, s:e], phase[:, s:e])
            X_list.append(feat)
            yt_list.append(total_label)
            file_list.append(str(fname))

        if i % 5 == 0 or i == len(unique_files):
            elapsed = time.time() - t0
            print(
                f"  [{i:>2}/{len(unique_files)}] {fname} "
                f"(total={total_label}) n_time={mag.shape[1]} "
                f"windows={len(idx_list)} | elapsed {elapsed:.1f}s"
            )

    X = np.vstack(X_list).astype(np.float32)
    y_total = np.asarray(yt_list, dtype=np.int32)
    file_per_window = np.asarray(file_list)

    print(
        f"Featurize done. X={X.shape}, y_total={y_total.shape}, "
        f"total time={time.time() - t0:.1f}s"
    )
    return X, y_total, file_per_window


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Featurize merged.npz ke preprocessed dataset.")
    parser.add_argument(
        "--merged",
        type=Path,
        default=MERGED_PATH,
        help=f"Path ke merged.npz (default: {MERGED_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_DIR / "featurized_dataset.npz",
        help="Path output .npz (default: /featurized_dataset.npz)",
    )
    parser.add_argument(
        "--features",
        choices=["mag", "phase", "both"],
        default="both",
        help="Feature components to extract: 'mag', 'phase', or 'both' (default: both)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print("=" * 64)
    print("Featurize merged.npz -> preprocessed dataset")
    print(f"  merged.npz : {args.merged}")
    print(f"  output     : {args.output}")
    print(f"  window     : {WINDOW_SIZE} / {WINDOW_STRIDE}")
    print(f"  features   : {args.features}")
    print(f"  delete sc  : {DELETE_SUBCARRIER_INDICES.tolist()}")
    print("=" * 64)

    print("\n[1] Loading merged.npz ...")
    merged = np.load(args.merged, allow_pickle=False)
    print(f"  csi          : {merged['csi'].shape}  {merged['csi'].dtype}")
    print(f"  unique files : {len(np.unique(merged['nama_file']))}")
    print(f"  total uniq   : {np.unique(merged['total_orang']).tolist()}")

    print("\n[2] Featurizing ...")
    X, y_total, file_per_window = featurize_all_files(merged, features=args.features)
    print(f"  label dist (per-window): {dict(zip(*np.unique(y_total, return_counts=True)))}")

    print(f"\n[3] Saving to {args.output} ...")
    np.savez_compressed(
        args.output,
        X=X,
        y_total=y_total,
        file_per_window=file_per_window,
        features=np.array(args.features),
    )
    print(f"  saved. X={X.shape} ({X.dtype}), y_total={y_total.shape}, "
          f"file_per_window={file_per_window.shape}, features={args.features}")
    print("\nDone.")


if __name__ == "__main__":
    main()
