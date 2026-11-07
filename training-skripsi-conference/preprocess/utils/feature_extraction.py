"""
Feature extraction utilities including windowing and statistical features.
"""

from typing import List, Tuple

import numpy as np

from .config import WINDOW_SIZE, WINDOW_STRIDE


def window_indices(
    n_time: int,
    window_size: int = None,
    stride: int = None
) -> List[Tuple[int, int]]:
    """
    Generate (start, end) indices untuk window sliding di domain waktu.
    
    Parameters
    ----------
    n_time : int
        Jumlah time steps total
    window_size : int, optional
        Ukuran window. Default: WINDOW_SIZE dari config
    stride : int, optional
        Stride antar window. Default: WINDOW_STRIDE dari config
        
    Returns
    -------
    List[Tuple[int, int]]
        List berisi tuple (start, end) untuk setiap window
    """
    if window_size is None:
        window_size = WINDOW_SIZE
    if stride is None:
        stride = WINDOW_STRIDE
        
    indices = []
    start = 0
    while start + window_size <= n_time:
        end = start + window_size
        indices.append((start, end))
        start += stride
    return indices


def extract_features_from_window(
    mag_win: np.ndarray,
    phase_win: np.ndarray = None,
) -> np.ndarray:
    """
    Ekstrak fitur statistik dari satu window (magnitude, dan opsional phase).

    Magnitude — distribusi amplitudo: mean, std, min, max, median.
    Phase (differential) — dinamika temporal: std, mean_abs, iqr,
        autocorr_lag1, max_abs. Mean dihindari karena differential phase
        bersifat zero-mean by construction.

    Parameters
    ----------
    mag_win : np.ndarray
        Magnitude window berukuran (n_subcarrier, window_size)
    phase_win : np.ndarray, optional
        Differential phase window berukuran (n_subcarrier, window_size).
        Jika None, hanya fitur magnitude yang diekstrak.

    Returns
    -------
    np.ndarray
        Vektor fitur 1D (flatten) siap untuk model ML
    """
    def _mag_stats(arr: np.ndarray) -> np.ndarray:
        feats = [
            np.mean(arr, axis=1),
            np.std(arr, axis=1),
            np.min(arr, axis=1),
            np.max(arr, axis=1),
            np.median(arr, axis=1),
        ]
        return np.stack(feats, axis=1)  # (n_subcarrier, 5)

    def _phase_stats(arr: np.ndarray) -> np.ndarray:
        # std: variabilitas differential phase — naik saat ada gerakan
        std = np.std(arr, axis=1)
        # mean_abs: mean |Δφ|, hindari pembatalan tanda pada mean biasa
        mean_abs = np.mean(np.abs(arr), axis=1)
        # iqr: spread robust terhadap spike hardware
        iqr = np.percentile(arr, 75, axis=1) - np.percentile(arr, 25, axis=1)
        # autocorr_lag1: korelasi antar paket berurutan; gerakan → lebih rendah
        x = arr - arr.mean(axis=1, keepdims=True)
        num = (x[:, :-1] * x[:, 1:]).sum(axis=1)
        den = (x ** 2).sum(axis=1)
        autocorr = np.where(den > 0, num / den, 0.0)
        # max_abs: lompatan fase terbesar dalam window
        max_abs = np.max(np.abs(arr), axis=1)

        feats = [std, mean_abs, iqr, autocorr, max_abs]
        return np.stack(feats, axis=1)  # (n_subcarrier, 5)

    mag_feats = _mag_stats(mag_win)

    if phase_win is not None:
        phase_feats = _phase_stats(phase_win)
        return np.concatenate([mag_feats.ravel(), phase_feats.ravel()])

    return mag_feats.ravel()
