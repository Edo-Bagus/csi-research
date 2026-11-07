#!/usr/bin/env python3
"""EDA data-15-9 dengan kontrol null yang benar.

Jalankan: python eda_15_9.py

KENAPA SKRIP INI ADA, BUKAN CUKUP NOTEBOOK
------------------------------------------
Tiga pertanyaan (deteksi, counting, zona) semuanya terlihat POSITIF kalau diukur
dengan cara biasa (effect size, akurasi, R2), dan semuanya runtuh di bawah kontrol
null. Kontrol itu harus ikut di repo supaya tidak hilang:

1. counting dalam satu sesi -> null LABEL YANG DIGESER SECARA SIRKULER.
   Distribusi dan autokorelasi label dipertahankan, kaitannya ke CSI dihancurkan.
   Tanpa ini, count_2_1 tampak berhasil (MAE 4.10 vs baseline 5.69) padahal
   label yang digeser justru lebih mudah diprediksi (3.64) -- itu autokorelasi,
   bukan penginderaan.
2. deteksi LOSO -> bandingkan ke KELAS MAYORITAS dan lihat rincian per sesi.
   Akurasi 0.933 persis sama dengan proporsi kelas mayoritas, dan count_2_9
   (satu-satunya sesi dengan jendela kosong) dapat 0.000: model menebak
   "terisi" untuk semuanya.
3. zona -> uji SEMUA 24 permutasi zona->board, bukan cuma denah pengguna vs
   rata-rata sisanya. Denah pengguna ada di peringkat 8/24, 4/24, 3/24, 20/24
   tergantung statistik; permutasi terbaik untuk rssi_std justru denah 14-9
   yang SALAH untuk ruangan ini. Itu pola yang dihasilkan kebetulan.
"""
import itertools
import warnings

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import (GroupKFold, LeaveOneGroupOut,
                                     cross_val_predict, cross_val_score)

from . import datasets as loader
from .paths import DATA_PROCESSED, ensure_output_dirs

warnings.filterwarnings("ignore")

DS = loader.DS_15_9
WIN_S, HOP_S = 2.0, 1.0
N_NULL = 5
RAMP_S = 120.0     # detik awal yang timestamp-nya tidak bisa dipercaya
CACHE = DATA_PROCESSED / "feat_15_9.csv"


def build(force=False):
    """Fitur per-jendela semua sesi 15-9, di-cache ke CSV."""
    ensure_output_dirs()
    if CACHE.exists() and not force:
        return pd.read_csv(CACHE)
    out = []
    for s in loader.list_sessions(ds=DS):
        df = loader.window_features(s, win_s=WIN_S, hop_s=HOP_S, ds=DS)
        print(f"  {s}: {len(df)} jendela, board {df['boards'].iloc[0]}", flush=True)
        out.append(df)
    feat = pd.concat(out, ignore_index=True)
    feat.to_csv(CACHE, index=False)
    return feat


def usable(feat):
    return feat[feat["_ok"] & feat["total"].notna()].copy()


def _mae(model, X, y, cv, groups):
    return -cross_val_score(model, X, y, cv=cv, groups=groups,
                            scoring="neg_mean_absolute_error", n_jobs=-1).mean()


def counting_within_session(f, feats, trim_ramp=True):
    """Counting di dalam satu sesi, diuji lawan null label-digeser."""
    rng = np.random.default_rng(0)
    print(f"\n--- counting dalam sesi (trim {RAMP_S:.0f}s awal = {trim_ramp}) ---")
    for s in sorted(f["session"].unique()):
        g = f[(f["session"] == s) & (f["total"] >= 10)].sort_values("t_start")
        if trim_ramp:
            g = g[(g["t_start"] - g["t_start"].min()) >= RAMP_S]
        if len(g) < 100 or g["total"].nunique() < 3:
            continue
        X = np.nan_to_num(g[feats].to_numpy(float))
        y = g["total"].to_numpy(float)
        n = len(g)
        blocks = np.arange(n) // max(1, n // 5)   # blok waktu, bukan acak
        cv = LeaveOneGroupOut()
        rf = RandomForestRegressor(n_estimators=150, random_state=0, n_jobs=-1)
        real = _mae(rf, X, y, cv, blocks)
        base = _mae(DummyRegressor(strategy="mean"), X, y, cv, blocks)
        nulls = [_mae(rf, X, np.roll(y, rng.integers(n // 5, n - n // 5)), cv, blocks)
                 for _ in range(N_NULL)]
        ok = real < min(nulls) and real < base
        print(f"  {s}: n={n:3d} sd={y.std():4.1f} real={real:5.2f} base={base:5.2f} "
              f"null={np.mean(nulls):5.2f}(min {min(nulls):.2f}) "
              f"=> {'REAL' if ok else 'tak terbedakan'}")


def detection_loso(f, feats):
    """Deteksi kosong-vs-terisi, dibandingkan ke kelas mayoritas."""
    print("\n--- deteksi kosong vs terisi (leave-one-session-out) ---")
    d = f[(f["total"] == 0) | (f["total"] >= 10)].copy()
    d["occupied"] = (d["total"] >= 10).astype(int)
    X = np.nan_to_num(d[feats].to_numpy(float))
    y = d["occupied"].to_numpy()
    g = d["session"].to_numpy()
    pred = cross_val_predict(
        RandomForestClassifier(n_estimators=300, random_state=0, n_jobs=-1),
        X, y, cv=LeaveOneGroupOut(), groups=g, n_jobs=-1)
    major = max(y.mean(), 1 - y.mean())
    print(f"  akurasi LOSO = {(pred == y).mean():.3f}  kelas mayoritas = {major:.3f}")
    for s in sorted(d["session"].unique()):
        m = g == s
        print(f"   {s:12s} kosong={int((y[m] == 0).sum()):4d} "
              f"terisi={int((y[m] == 1).sum()):4d} akurasi={(pred[m] == y[m]).mean():.3f}")
    print("  PERINGATAN: hampir semua jendela kosong berasal dari SATU sesi, jadi")
    print("  'kosong' praktis identik dengan 'sesi itu' -- angka ini ikut mengukur")
    print("  pembedaan sesi, bukan okupansi murni.")


def zone_permutations(f):
    """Denah zona pengguna vs SEMUA 24 permutasi."""
    print("\n--- kopling zona-board: denah pengguna vs 24 permutasi ---")
    occ = f[f["total"] >= 10]
    boards = list(DS.zone_board.values())

    def score(mapping, stat):
        vals = []
        for z, b in mapping.items():
            c = f"{b}_{stat}"
            if c not in occ or occ[z].std() == 0:
                continue
            r = abs(np.corrcoef(occ[c].fillna(occ[c].median()), occ[z])[0, 1])
            if not np.isnan(r):
                vals.append(r)
        return float(np.mean(vals)) if vals else np.nan

    for stat in ["rssi_mean", "rssi_std", "amp_mean", "sub_var"]:
        us = score(DS.zone_board, stat)
        allp = [score(dict(zip(loader.ZONES, p)), stat)
                for p in itertools.permutations(boards)]
        rank = 1 + sum(1 for v in allp if v > us)
        print(f"  {stat:10s} denah_pengguna={us:.3f} peringkat {rank}/{len(allp)} "
              f"(terbaik {max(allp):.3f})")
    r_ct = np.corrcoef(occ["C"], occ["total"])[0, 1]
    print(f"  Zona juga naik bersama-sama saat ruangan terisi (corr(C,total)={r_ct:+.2f}),")
    print("  jadi korelasi board-zona sebagian besar adalah confound jumlah total.")


def main():
    print("== membangun fitur data-15-9 ==")
    f = usable(build())
    feats = [c for c in f.columns
             if any(c.endswith("_" + s) for s in loader.STATS)]
    print(f"{len(f)} jendela terpakai, {len(feats)} fitur, "
          f"{f['session'].nunique()} sesi")

    X = np.nan_to_num(f[feats].to_numpy(float))
    acc = cross_val_score(RandomForestClassifier(n_estimators=200, random_state=0,
                                                 n_jobs=-1),
                          X, f["session"].to_numpy(), cv=5, n_jobs=-1).mean()
    print(f"\n--- confound: akurasi menebak SESI = {acc:.3f} "
          f"(acak {1 / f['session'].nunique():.3f}) ---")

    occ = f[f["total"] >= 10]
    Xo = np.nan_to_num(occ[feats].to_numpy(float))
    yo = occ["total"].to_numpy(float)
    go = occ["session"].to_numpy()
    k = occ["session"].nunique()
    print("\n--- counting antar-sesi (GroupKFold per sesi) ---")
    rf = _mae(RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=-1),
              Xo, yo, GroupKFold(n_splits=k), go)
    bs = _mae(DummyRegressor(strategy="mean"), Xo, yo, GroupKFold(n_splits=k), go)
    print(f"  RF MAE={rf:.2f} orang  baseline rata-rata={bs:.2f}  "
          f"sd label={yo.std():.1f}")

    counting_within_session(f, feats, trim_ramp=False)
    counting_within_session(f, feats, trim_ramp=True)
    detection_loso(f, feats)
    zone_permutations(f)


if __name__ == "__main__":
    main()
