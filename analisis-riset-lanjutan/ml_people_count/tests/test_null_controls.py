"""Tes untuk KONTROL NULL-nya sendiri.

Kesimpulan negatif proyek ini ("counting tidak terjawab") hanya bisa dipercaya
kalau kontrol null-nya benar-benar bekerja. Jadi kontrolnya sendiri harus diuji:

- diberi sinyal PALSU (label yang benar-benar terkait fitur), kontrol harus LOLOS.
- diberi label acak berautokorelasi, kontrol harus MENOLAK.

Tanpa tes ini, "null-nya tidak terlampaui" bisa berarti dua hal yang sangat
berbeda: tidak ada sinyal, atau kontrolnya rusak.
"""
import numpy as np
import pandas as pd
from scipy import stats


def _autocorrelated(n, rng, rho=0.99):
    """Deret acak yang mulus (mirip label okupansi: berubah lambat)."""
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + rng.normal()
    return x


def test_circular_shift_preserves_distribution_and_autocorrelation():
    """Null yang dipakai adalah np.roll. Itu harus mempertahankan distribusi DAN
    autokorelasi label -- kalau tidak, null-nya terlalu mudah dan hasil apa pun
    tampak signifikan."""
    rng = np.random.default_rng(0)
    y = _autocorrelated(2000, rng)
    ys = np.roll(y, 613)
    assert np.allclose(np.sort(y), np.sort(ys))          # distribusi identik
    a_real = np.corrcoef(y[:-1], y[1:])[0, 1]
    a_shift = np.corrcoef(ys[:-1], ys[1:])[0, 1]
    assert abs(a_real - a_shift) < 0.01                  # autokorelasi ~sama


def test_shift_null_detects_a_genuinely_fake_signal():
    """Kalau label TIDAK terkait fitur, model tidak boleh mengalahkan null.

    Ini yang terjadi di count_2_1: MAE asli 4.10 tapi null-nya 3.64.
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneGroupOut, cross_val_score
    rng = np.random.default_rng(1)
    n = 400
    X = rng.normal(size=(n, 6))                 # fitur murni derau
    y = _autocorrelated(n, rng)                 # label mulus, TIDAK terkait X
    blocks = np.arange(n) // (n // 5)

    def mae(yy):
        return -cross_val_score(
            RandomForestRegressor(n_estimators=40, random_state=0),
            X, yy, cv=LeaveOneGroupOut(), groups=blocks,
            scoring="neg_mean_absolute_error").mean()

    real = mae(y)
    nulls = [mae(np.roll(y, rng.integers(n // 5, n - n // 5))) for _ in range(5)]
    # tanpa sinyal nyata, model TIDAK boleh lebih baik dari semua null
    assert real >= min(nulls), "kontrol null gagal menangkap sinyal palsu"


def test_shift_null_passes_a_real_signal():
    """Sebaliknya: kalau label BENAR-BENAR terkait fitur, null harus dilampaui.
    Kalau tes ini gagal, kontrolnya terlalu ketat dan akan membuang hasil nyata."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneGroupOut, cross_val_score
    rng = np.random.default_rng(2)
    n = 400
    y = _autocorrelated(n, rng)
    # fitur yang benar-benar membawa y (plus sedikit derau)
    X = np.column_stack([y + rng.normal(scale=0.3, size=n) for _ in range(4)])
    blocks = np.arange(n) // (n // 5)

    def mae(yy, XX=X):
        return -cross_val_score(
            RandomForestRegressor(n_estimators=40, random_state=0),
            XX, yy, cv=LeaveOneGroupOut(), groups=blocks,
            scoring="neg_mean_absolute_error").mean()

    real = mae(y)
    nulls = [mae(np.roll(y, rng.integers(n // 5, n - n // 5))) for _ in range(5)]
    assert real < min(nulls), "kontrol null menolak sinyal yang nyata"


def test_majority_class_baseline_is_computed_not_assumed():
    """Akurasi 0.933 pada deteksi = persis kelas mayoritas. Perbandingan itu
    harus selalu ikut dilaporkan, jadi hitungannya diuji di sini."""
    y = np.array([1] * 4687 + [0] * 336)
    major = max(y.mean(), 1 - y.mean())
    assert abs(major - 0.933) < 0.001


def test_permutation_pvalue_is_one_sided_and_inclusive():
    """p = proporsi null >= observed. Harus inklusif (>=), bukan (>) -- kalau
    tidak, p bisa jadi 0 dan itu klaim yang tidak bisa dipertahankan."""
    null = np.array([0, 1, 1, 2, 4])
    observed = 4
    p = (null >= observed).mean()
    assert p == 0.2
    assert p > 0, "p-value tidak boleh 0 dengan permutasi berhingga"


def test_spearman_used_for_small_n_not_pearson():
    """n=7-9 sesi: satu outlier bisa membuat Pearson apa saja. Analisis tingkat
    sesi memakai Spearman (rank). Tes ini mendemonstrasikan kenapa."""
    x = np.array([1., 2, 3, 4, 5, 6, 100])
    y = np.array([1., 2, 3, 4, 5, 6, 7])
    assert stats.spearmanr(x, y)[0] == 1.0          # rank: sempurna
    assert stats.pearsonr(x, y)[0] < 0.85           # Pearson: dirusak outlier
