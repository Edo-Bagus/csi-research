#!/usr/bin/env python3
"""Koherensi temporal CSI: temuan terkuat dari kedua dataset.

Jalankan: python coherence.py

TEMUAN
------
Okupansi tidak sekadar MENAMBAH variance, tapi menambah variance YANG PUNYA
STRUKTUR WAKTU. Diukur sebagai autokorelasi lag-k amplitudo per subcarrier
(dirata-rata atas subcarrier aktif, hanya jendela plateau):

  17 sesi berpenghuni : koherensi@1s = 0.356 .. 0.572  (mean 0.495)
   2 sesi kosong      : 0.146 (count_s10) dan 0.052 (count_2_9)

TIDAK ADA TUMPANG-TINDIH: kosong maksimum (0.146) < berpenghuni minimum (0.356).
Rasio 5x. Mann-Whitney p=0.0058. Berlaku di KEDUA ruangan secara independen.

MEKANISME -- ini bagian yang bisa ditafsirkan
---------------------------------------------
Kurva autokorelasi lengkap menjelaskan kenapa:
  KOSONG      : jatuh ke nol dalam 1-2 paket, lalu datar (~0.05 sampai lag 800).
                Variasinya bebas antar-sampel = derau penerima/termal.
  BERPENGHUNI : tetap berkorelasi ratusan paket. r1 N=16: 0.56 -> 0.40@1s -> 0.16@10s.
                r2 N=72: 0.68 -> 0.51@1s -> 0.21@20s.

Jadi tubuh manusia menyuntikkan proses fisik dengan SKALA WAKTU sendiri (orang
bergeser, bergerak, bernapas). Ini sekaligus menjelaskan kenapa `sub_var` biasa
lemah padahal flux dan koherensi bekerja: variance saja tidak bisa membedakan
derau dari struktur.

ARTEFAK YANG SUDAH DISINGKIRKAN
------------------------------
1. Bukan laju paket: 41-45 Hz di semua sesi, jadi 40 paket ~= 1 s di semuanya.
2. Bukan noise floor/SNR: kedua sesi kosong ada di -53.2 dBm, yaitu DI DALAM
   rentang sesi berpenghuni (-54.6 .. -48.8). count_s05 (-54.6) dan count_2_8
   (-54.1) RSSI-nya LEBIH LEMAH dari sesi kosong tapi koherensinya 3-8x lebih
   tinggi. Amplitudo rata-rata juga setara (20.4 kosong vs 19.9 berpenghuni).
3. Nyaris tidak terkena confound jam: corr(koherensi, jam) = +0.25 (14-9) dan
   -0.45 (15-9). Bandingkan fitur LEVEL yang mati total di kontrol ini
   (lihat session_level.py).

YANG TETAP TIDAK BISA DIKLAIM
-----------------------------
Di antara sesi berpenghuni saja, koherensi-vs-N: rho=+0.16 (14-9), -0.22 (15-9),
keduanya tidak signifikan. Kehadiran terdeteksi, JUMLAH ORANG tidak.

CAVEAT YANG WAJIB DITULIS
-------------------------
Hanya ada 2 sesi kosong, satu per ruangan, masing-masing direkam di waktu berbeda
dari sesi berpenghuni di ruangan yang sama. Pemisahan tanpa tumpang-tindih dan
argumen mekanismenya kuat, tapi sampel sesi kosong tetap n=2.
"""
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from . import datasets as loader
from .paths import DATA_PROCESSED, RESULTS_TABLES, ensure_output_dirs

warnings.filterwarnings("ignore")

RAMP_S = 120.0
LAGS = [1, 2, 5, 10, 20, 40, 80, 200, 400, 800]
LAG_1S = 40          # ~1 s pada 40-45 Hz
SUB_STRIDE = 8       # subsample subcarrier supaya cepat; hasilnya stabil


def active(amp):
    """Subcarrier yang benar-benar membawa energi."""
    a = amp.mean(axis=0)
    return a > 0.05 * a.max()


def autocorr_curve(amp, lags=LAGS, stride=SUB_STRIDE):
    """Autokorelasi rata-rata atas subcarrier aktif, untuk tiap lag."""
    L = amp[:, active(amp)]
    L = (L - L.mean(0)) / (L.std(0) + 1e-9)
    out = []
    for k in lags:
        if len(L) < k + 100:
            out.append(np.nan)
            continue
        vals = [np.corrcoef(L[:-k, j], L[k:, j])[0, 1]
                for j in range(0, L.shape[1], stride)]
        out.append(float(np.nanmean(vals)))
    return out


def plateau_amp(d):
    """Amplitudo setelah ramp awal dibuang (timestamp ramp tidak dipercaya)."""
    t = d["t"]
    m = t >= t.min() + RAMP_S
    if m.sum() < 2000:
        m = np.ones(len(t), bool)
    return d["amp"][m]


def session_coherence(ds, sess):
    """Koherensi@1s tiap board + RSSI + laju paket untuk satu sesi."""
    n = loader.load_session(sess, ds=ds)
    per_board, rssi, rate = {}, [], []
    for tag, d in n.items():
        amp = plateau_amp(d)
        c = autocorr_curve(amp, lags=[LAG_1S])[0]
        if not np.isnan(c):
            per_board[tag] = c
        rssi.append(float(d["rssi"].mean()))
        t = d["t"]
        rate.append(len(t) / (t.max() - t.min()))
    return per_board, float(np.mean(rssi)), float(np.mean(rate))


def plateau_N(cache):
    """Okupansi plateau tiap sesi, dari fitur per-jendela yang sudah ada."""
    path = DATA_PROCESSED / cache
    if not path.exists():
        return {}
    f = pd.read_csv(path)
    f = f[f["_ok"] & f["total"].notna()]
    out = {}
    for s, g in f.groupby("session"):
        g = g.sort_values("t_start")
        t = g["t_start"] - g["t_start"].min()
        pl = g[t >= RAMP_S] if (t >= RAMP_S).sum() >= 50 else g
        out[s] = pl["total"].median()
    return out


def build():
    NS = {}
    for c in ["feat_14_9.csv", "feat_15_9.csv"]:
        NS.update(plateau_N(c))
    rows = []
    for ds in [loader.DS_14_9, loader.DS_15_9]:
        for s in loader.list_sessions(ds=ds):
            pb, rssi, rate = session_coherence(ds, s)
            if not pb:
                continue
            rows.append({"room": ds.name, "session": s, "N": NS.get(s, np.nan),
                         "coh": float(np.mean(list(pb.values()))),
                         "rssi": rssi, "rate": rate,
                         "boards": ",".join(sorted(pb))})
            print(f"  {ds.name} {s}: N={rows[-1]['N']:5.1f} "
                  f"coh@1s={rows[-1]['coh']:+.3f} rssi={rssi:.1f}", flush=True)
    return pd.DataFrame(rows)


def main():
    print("== koherensi temporal per sesi ==")
    T = build()
    T = T.dropna(subset=["N"])
    ensure_output_dirs()
    out = RESULTS_TABLES / "coherence_summary.csv"
    T.to_csv(out, index=False)
    print(f"  -> {out.relative_to(out.parents[2])}")

    emp, occ = T[T["N"] == 0], T[T["N"] > 0]
    print("\n--- kosong vs berpenghuni ---")
    print(f"  kosong      (n={len(emp)}): {emp['coh'].round(3).tolist()}")
    print(f"  berpenghuni (n={len(occ)}): mean {occ['coh'].mean():.3f}, "
          f"rentang {occ['coh'].min():.3f}-{occ['coh'].max():.3f}")
    if len(emp) and len(occ):
        print(f"  rasio {occ['coh'].mean() / emp['coh'].mean():.1f}x   "
              f"tanpa tumpang-tindih: {emp['coh'].max() < occ['coh'].min()}")
        u = stats.mannwhitneyu(occ["coh"], emp["coh"], alternative="greater")
        print(f"  Mann-Whitney p={u.pvalue:.4f}")

    print("\n--- apakah koherensi menghitung ORANG? (di antara yang berpenghuni) ---")
    for room, g in occ.groupby("room"):
        r, p = stats.spearmanr(g["coh"], g["N"])
        print(f"  {room}: rho={r:+.3f} p={p:.3f} (n={len(g)}) -> "
              f"{'ADA' if p < 0.05 else 'TIDAK ada'} kaitan dengan jumlah")

    print("\n--- singkirkan artefak ---")
    print(f"  laju paket semua sesi: {T['rate'].min():.1f}-{T['rate'].max():.1f} Hz "
          f"-> {LAG_1S} paket ~= 1 s di semuanya")
    print(f"  RSSI kosong      : {emp['rssi'].round(1).tolist()}")
    print(f"  RSSI berpenghuni : {occ['rssi'].min():.1f} .. {occ['rssi'].max():.1f}")
    weaker = occ[occ["rssi"] < emp["rssi"].max()]
    print(f"  sesi berpenghuni dengan RSSI LEBIH LEMAH dari sesi kosong: "
          f"{len(weaker)} ({', '.join(weaker['session'])})")
    if len(weaker):
        print(f"     koherensinya {weaker['coh'].min():.3f}-{weaker['coh'].max():.3f} "
              f"-> tetap jauh di atas kosong. Jadi bukan efek SNR.")

    print("\n--- kurva autokorelasi lengkap (mekanisme) ---")
    for ds, sess, lab in [(loader.DS_14_9, "count_s10", "r1 KOSONG "),
                          (loader.DS_14_9, "count_s07", "r1 N=16   "),
                          (loader.DS_15_9, "count_2_9", "r2 KOSONG "),
                          (loader.DS_15_9, "count_2_7", "r2 N=72   ")]:
        n = loader.load_session(sess, ds=ds)
        tag = "4b" if "4b" in n else sorted(n)[0]
        cur = autocorr_curve(plateau_amp(n[tag]), stride=16)
        print(f"  {lab} " + "  ".join(f"{k}:{v:+.2f}" for k, v in zip(LAGS, cur)))
    print(f"  (lag dalam paket; {LAG_1S} paket ~= 1 s)")
    print("  KOSONG jatuh ke derau dalam 1-2 paket lalu datar -> variasi bebas")
    print("  antar-sampel. BERPENGHUNI bertahan ratusan paket -> proses fisik")
    print("  dengan skala waktu sendiri. Itulah sifat yang membedakan.")


if __name__ == "__main__":
    main()
