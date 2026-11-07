#!/usr/bin/env python3
"""Analisis TINGKAT SESI untuk kedua ruangan: apa yang masih bisa diklaim.

Jalankan: python session_level.py

KENAPA TINGKAT SESI, BUKAN PER JENDELA
--------------------------------------
Analisis per jendela gagal di kedua ruangan (lihat eda_15_9.py): okupansi nyaris
konstan di dalam satu sesi, jadi tidak ada variasi untuk dikorelasikan. Tapi yang
DISAMPEL BAIK oleh kedua dataset adalah SESI-nya: 19 sesi dengan tingkat okupansi
berbeda-beda, 0..72 orang. data-14-9 mengisi ujung sepi (0,7,9,12-16), data-15-9
mengisi ujung padat (0,45,60,68-72). Digabung, rentangnya nyata; sendiri-sendiri
tidak.

DUA HASIL, DAN KENAPA SATU DIBUANG
----------------------------------
1. FITUR LEVEL (median amp/rssi/var per sesi) -- DIBUANG.
   Tampak sangat kuat: 4b_sub_std_spatial rho=-0.917 (14-9) dan -0.903 (15-9),
   replikasi lintas ruangan, permutation p=0.0025. TAPI sesi direkam berurutan
   sementara ruangan terisi, jadi corr(jam, N) = +0.95 dan +0.83. Begitu waktu
   di-partial-out, rho jatuh ke -0.36 / -0.31 -- tidak signifikan di n=7-8.
   Artinya: tak bisa dibedakan dari drift kanal sepanjang siang. JANGAN dilaporkan
   sebagai penginderaan okupansi.

2. FITUR DINAMIKA (flux) -- DIPAKAI.
   Didefinisikan sebagai mean|selisih 1 langkah| / mean level. Karena berupa
   SELISIH pada skala ~1 detik, drift skala jam hilang DENGAN SENDIRINYA. Inilah
   sifat yang tidak dimiliki fitur level.
   - 16 dari 18 korelasi flux-vs-N bertanda POSITIF (binomial p=0.0007): makin
     banyak orang, makin cepat CSI berfluktuasi. Ini prediksi berarah, bukan
     sekadar "ada korelasi".
   - 38_rssi_mean_flux (+0.698/+0.659) dan 38_sub_var_flux (+0.536/+0.586)
     replikasi lintas ruangan dengan tanda sama; permutation p=0.0105.
   - Autokorelasi CSI turun cepat (lag-1 ~0.7, lag-30 ~0.0): fluktuasi detik-an
     yang nyata, bukan drift lambat.
   - CAVEAT YANG HARUS DITULIS: partial correlation lolos di 14-9 (+0.63,+0.65,
     +0.58) tapi NEGATIF di 15-9. Jadi ini sugestif, belum tuntas.

JANGAN GABUNG RUANGAN. Pooled rho = +0.07 (tak berarti) karena level fitur beda
antar ruangan. Klaim selalu per ruangan, lalu replikasi tanda sebagai buktinya.
Framing "ruangan 1 sepi vs ruangan 2 padat" memberi LOSO 0.999 tapi TIDAK SAH:
ruangan dan tingkat keramaian kolinier sempurna.
"""
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from . import datasets as loader
from .paths import DATA_PROCESSED, ensure_output_dirs

warnings.filterwarnings("ignore")

RAMP_S = 120.0          # detik awal dengan timestamp label tak dipercaya
BOARDS = ["38", "4b", "d0"]     # bf tidak ada di dua sesi 14-9
N_PERM = 2000


def features_for(ds, cache):
    """Fitur per-jendela satu dataset, di-cache ke CSV."""
    ensure_output_dirs()
    path = DATA_PROCESSED / cache
    if path.exists():
        f = pd.read_csv(path)
    else:
        out = []
        for s in loader.list_sessions(ds=ds):
            out.append(loader.window_features(s, ds=ds))
            print(f"  {s}", flush=True)
        f = pd.concat(out, ignore_index=True)
        f.to_csv(path, index=False)
    f = f[f["_ok"] & f["total"].notna()].copy()
    f["room"] = ds.name
    return f


def plateau(g):
    """Buang ramp awal; timestamp di dalamnya adalah kelambatan input manual."""
    t = g["t_start"] - g["t_start"].min()
    return g[t >= RAMP_S] if (t >= RAMP_S).sum() >= 50 else g


def session_dynamics(f):
    """Satu baris per sesi: laju fluktuasi CSI (flux) + okupansi + jam mulai."""
    rows = []
    for s, g in f.groupby("session"):
        g = g.sort_values("t_start")
        pl = plateau(g)
        if len(pl) < 60:
            continue
        r = {"room": pl["room"].iloc[0], "session": s,
             "N": pl["total"].median(), "n_win": len(pl),
             "t0": g["t_start"].min()}
        for b in BOARDS:
            for stat in ["sub_var", "amp_mean", "rssi_mean"]:
                c = f"{b}_{stat}"
                if c not in pl:
                    continue
                v = pl[c].to_numpy(float)
                v = v[~np.isnan(v)]
                if len(v) < 60:
                    continue
                # selisih 1 langkah, dinormalisasi ke level -> bebas skala,
                # dan drift skala jam hilang karena ini beda antar-jendela.
                r[f"{b}_{stat}_flux"] = np.mean(np.abs(np.diff(v))) / (np.mean(np.abs(v)) + 1e-9)
        rows.append(r)
    return pd.DataFrame(rows)


def flux_cols(D):
    return [c for c in D.columns if c.endswith("_flux")]


def report_per_room(D):
    print("\n--- flux vs jumlah orang, per ruangan ---")
    for room, g in D.groupby("room"):
        print(f"  {room} (n={len(g)} sesi, N={sorted(g['N'].astype(int))})")
        for c in flux_cols(D):
            if g[c].isna().any():
                continue
            r, p = stats.spearmanr(g[c], g["N"])
            if abs(r) > 0.6:
                print(f"    {c:24s} rho={r:+.3f} p={p:.3f}"
                      f"{'*' if p < 0.05 else ''}")


def cross_room_replication(D, thresh=0.5):
    """Fitur yang bertanda SAMA dan |rho|>thresh di KEDUA ruangan."""
    hits = []
    for c in flux_cols(D):
        rr = {}
        for room, g in D.groupby("room"):
            if g[c].isna().any():
                rr[room] = np.nan
                continue
            rr[room] = stats.spearmanr(g[c], g["N"])[0]
        x, y = rr.get("data-14-9", np.nan), rr.get("data-15-9", np.nan)
        if np.isnan(x) or np.isnan(y):
            continue
        if np.sign(x) == np.sign(y) and min(abs(x), abs(y)) > thresh:
            hits.append((c, x, y))
    return hits


def permutation_test(D, thresh=0.5, n=N_PERM, seed=1):
    """Null: acak label N DI DALAM tiap ruangan, hitung ulang replikasi."""
    rng = np.random.default_rng(seed)

    def count(perm):
        k = 0
        for c in flux_cols(D):
            rr = {}
            for room, g in D.groupby("room"):
                if g[c].isna().any():
                    rr[room] = np.nan
                    continue
                y = g["N"].to_numpy(float)
                if perm:
                    y = rng.permutation(y)
                rr[room] = stats.spearmanr(g[c], y)[0]
            x, y2 = rr.get("data-14-9", np.nan), rr.get("data-15-9", np.nan)
            if np.isnan(x) or np.isnan(y2):
                continue
            if np.sign(x) == np.sign(y2) and min(abs(x), abs(y2)) > thresh:
                k += 1
        return k

    real = count(False)
    null = np.array([count(True) for _ in range(n)])
    return real, null


def sign_test(D):
    """Uji berarah: 'lebih banyak orang -> flux lebih tinggi' (positif)."""
    signs = []
    for c in flux_cols(D):
        for _, g in D.groupby("room"):
            if g[c].isna().any():
                continue
            signs.append(np.sign(stats.spearmanr(g[c], g["N"])[0]))
    signs = np.array(signs)
    pos = int((signs > 0).sum())
    p = stats.binomtest(pos, len(signs), 0.5, alternative="greater").pvalue
    return pos, len(signs), p


def clock_confound(D):
    """Kontrol yang MEMBUNUH fitur level: partial-out jam mulai sesi."""
    print("\n--- kontrol confound jam (yang membunuh fitur level) ---")
    for room, g in D.groupby("room"):
        hrs = ((g["t0"] - g["t0"].min()) / 3600).to_numpy(float)
        rho_tn = stats.spearmanr(hrs, g["N"])[0]
        print(f"  {room}: corr(jam, N) = {rho_tn:+.3f}")
        for c in flux_cols(D):
            if g[c].isna().any():
                continue
            rn = stats.spearmanr(g[c], g["N"])[0]
            if abs(rn) < 0.6:
                continue
            fv = g[c].to_numpy(float)
            nv = g["N"].to_numpy(float)
            rf = fv - np.polyval(np.polyfit(hrs, fv, 1), hrs)
            rnn = nv - np.polyval(np.polyfit(hrs, nv, 1), hrs)
            pr = stats.spearmanr(rf, rnn)[0]
            print(f"    {c:24s} vs N={rn:+.3f}  "
                  f"vs jam={stats.spearmanr(g[c], hrs)[0]:+.3f}  partial={pr:+.3f}")


def main():
    print("== fitur per-jendela kedua ruangan ==")
    A = features_for(loader.DS_14_9, "feat_14_9.csv")
    B = features_for(loader.DS_15_9, "feat_15_9.csv")

    D = pd.concat([session_dynamics(A), session_dynamics(B)], ignore_index=True)
    D = D[D["N"] > 0].reset_index(drop=True)
    print(f"\n{len(D)} sesi berpenghuni, {len(flux_cols(D))} fitur dinamika")
    for room, g in D.groupby("room"):
        print(f"  {room}: N = {sorted(g['N'].astype(int))}")

    report_per_room(D)

    print("\n--- replikasi lintas ruangan (tanda sama, |rho|>0.5 di keduanya) ---")
    for c, x, y in sorted(cross_room_replication(D),
                          key=lambda t: -min(abs(t[1]), abs(t[2]))):
        print(f"  {c:24s} 14-9={x:+.3f}  15-9={y:+.3f}")

    real, null = permutation_test(D)
    print(f"\n--- permutation null ({N_PERM} acak) ---")
    print(f"  teramati={real}  null mean={null.mean():.2f}  "
          f"p={(null >= real).mean():.4f}")

    pos, tot, p = sign_test(D)
    print("\n--- uji tanda berarah (hipotesis: lebih ramai -> flux naik) ---")
    print(f"  {pos}/{tot} korelasi flux-vs-N POSITIF, binomial p={p:.4f}")
    print("  Arah konsisten di dua ruangan, dua hari, dua rentang okupansi")
    print("  yang tidak tumpang-tindih -- itu bukan pola yang dihasilkan drift.")

    clock_confound(D)

    print("\n--- yang HARUS ikut ditulis ---")
    print("  partial correlation lolos di 14-9 tapi NEGATIF di 15-9, jadi hasil ini")
    print("  SUGESTIF, bukan tuntas. Jangan mengklaim counting.")


if __name__ == "__main__":
    main()
