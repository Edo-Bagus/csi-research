#!/usr/bin/env python3
"""Lokalisasi kasar 4-sudut dari CSI multi-node: baseline amplitudo + RSSI.

PERTANYAAN YANG DIJAWAB: dari empat board di empat sudut ruangan, di kuadran
mana orang berada? Bukan koordinat (x, y) -- hanya sudut terdekat.

---------------------------------------------------------------------------
GEOMETRI, DAN APA YANG SEBENARNYA DIUKUR
---------------------------------------------------------------------------

Router ada di TENGAH ruangan; keempat board ada di sudut. Artinya setiap board
mengukur kanal `router -> board`, yaitu satu garis radial dari pusat ke sudut.
Orang mengganggu CSI sebuah board ketika ia memotong garis itu -- bukan ketika
ia sekadar berdiri dekat board-nya.

Konsekuensinya, yang bisa dipulihkan di sini adalah ARAH (bearing) dari router,
bukan JARAK. Berdiri di tengah jalur router->4b dan berdiri tepat di board 4b
menghasilkan gangguan yang mirip pada 4b. Itu batas metode ini dan bukan bug;
laporkan apa adanya.

---------------------------------------------------------------------------
POLARITAS: TIDAK DIASUMSIKAN, TAPI DIUKUR
---------------------------------------------------------------------------

Ada dua kemungkinan fisika saat tubuh memotong jalur, dan keduanya nyata:

  - SHADOWING  : tubuh menyerap, amplitudo board itu TURUN.
  - SCATTERING : tubuh memantulkan, energi multipath bertambah, amplitudo NAIK.

Di ruangan kecil dengan pantulan kuat, arah yang menang tidak bisa ditebak dari
teori saja. Maka skrip ini TIDAK berasumsi. Polaritas ditentukan dari capture
statik (`--static`), tempat setiap sudut ditempati bergantian dalam urutan yang
diketahui: untuk tiap board dilihat apakah deviasinya positif atau negatif saat
orang ada di sudut itu, lalu tandanya dipakai untuk seluruh analisis jalan.
Kalau `--static` tidak diberikan, polaritas diasumsikan shadowing (turun) dan
skrip mencetak peringatan -- hasilnya masih terbaca, tapi bisa terbalik.

---------------------------------------------------------------------------
NORMALISASI: KENAPA WAJIB
---------------------------------------------------------------------------

RSSI keempat board terentang -32..-46 dBm dan amplitudo CSI-nya ikut berbeda
jauh -- itu murni soal jarak ke router dan orientasi antena, bukan soal orang.
Membandingkan amplitudo mentah antar board hanya akan menghasilkan "board yang
paling dekat router selalu menang". Karena itu tiap board dinormalisasi terhadap
statistiknya SENDIRI dari capture kosong (`--baseline`):

    z_node(t) = (amp_node(t) - median_kosong_node) / MAD_kosong_node

MAD (median absolute deviation) dipakai, bukan std, karena baseline pendek dan
satu lonjakan interferensi sudah cukup untuk menggelembungkan std dan mengecilkan
semua z sesudahnya.

Pemakaian:

    # 1. periksa capture statik dulu -- ini yang menentukan polaritas
    python tools\\localize_baseline.py capture\\loc_static \\
        --baseline capture\\loc_baseline --static-mode

    # 2. analisis jalan memutar
    python tools\\localize_baseline.py capture\\loc_walk \\
        --baseline capture\\loc_baseline --static capture\\loc_static \\
        --markers capture\\loc_walk\\markers.csv --plot walk.png
"""

import argparse
import glob
import os
import sys
from collections import defaultdict

import numpy as np

# csi_merge.py ada di folder yang sama; pakai pembacanya supaya format frame
# hanya didefinisikan di satu tempat. Frame tidak punya version field, jadi
# menduplikasi struct di sini justru mengundang mismatch diam-diam.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csi_merge import read_bin  # noqa: E402

# Urutan jalan yang disepakati: 4b (kanan-bawah) -> bf (kanan-atas)
# -> 38 (kiri-atas) -> d0 (kiri-bawah) -> kembali ke 4b.
CORNER_ORDER = ["4b", "bf", "38", "d0"]
CORNER_DESC = {
    "4b": "kanan-bawah",
    "bf": "kanan-atas",
    "38": "kiri-atas",
    "d0": "kiri-bawah",
}

SIG_LEN = 114  # v2: hanya frame ICMP echo reply; lihat KNOWLEDGE.md


def node_tag(rec):
    """Nama pendek board ('4b', 'bf', '38', 'd0') = field node_id sebagai hex.

    PENTING: ini node_id, BUKAN byte terakhir MAC. Firmware menurunkannya dengan
    mem-fold dua byte terakhir MAC (`node_id_from_mac()` di app_main.c), jadi
    board `588c:8142:0b40` bernama `4b` karena 0x0b ^ 0x40 = 0x4b. Nama file
    .bin dari kolektor memakai konvensi yang sama, sehingga label di sini,
    nama file, dan log monitor semuanya cocok.
    """
    return f"{rec['node_id']:02x}"


def csi_amplitude(csi):
    """Amplitudo rata-rata seluruh subcarrier dari satu paket.

    Buffer CSI berisi pasangan (imag, real) int16 berselang-seling, 256 subcarrier
    untuk len=512. Subcarrier nol (guard/DC) ikut terbawa dan amplitudonya 0;
    dibiarkan saja karena jumlahnya tetap di semua paket, jadi hanya menggeser
    skala -- dan skala itu dihapus oleh normalisasi baseline.
    """
    a = np.asarray(csi, dtype=np.float64)
    if a.size < 2:
        return 0.0
    imag = a[0::2]
    real = a[1::2]
    return float(np.mean(np.hypot(real, imag)))


def load_session(indir, bin_ms, min_pkt=1):
    """Baca satu folder capture -> dict per node berisi deret waktu per bin.

    Mengembalikan (per_node, t0) dengan per_node[tag] = dict berisi array
    't' (detik relatif), 'amp', 'rssi', semuanya sudah dirata-rata per bin.
    """
    files = sorted(glob.glob(os.path.join(indir, "*.bin")))
    if not files:
        raise SystemExit(f"tidak ada .bin di {indir}")

    per_node = defaultdict(list)
    n_skipped = 0
    for path in files:
        for rec in read_bin(path):
            if rec["sig_len"] != SIG_LEN:
                n_skipped += 1
                continue
            per_node[node_tag(rec)].append(rec)
    if not per_node:
        raise SystemExit(f"tidak ada paket sig_len={SIG_LEN} di {indir}")

    # Rekonstruksi waktu capture sama persis dengan csi_merge.py: jam board
    # (presisi) digeser ke jam laptop (bisa dibandingkan antar node) dengan satu
    # offset per node, diambil dari persentil-10 supaya tidak tertarik ekor.
    for rs in per_node.values():
        rs.sort(key=lambda r: r["uptime_us"])
        deltas = sorted(r["host_time"] - r["uptime_us"] / 1e6 for r in rs)
        offset = deltas[max(0, int(0.10 * len(deltas)) - 1)]
        for r in rs:
            r["t_capture"] = r["uptime_us"] / 1e6 + offset

    t0 = min(r["t_capture"] for rs in per_node.values() for r in rs)
    bin_s = bin_ms / 1000.0

    out = {}
    for tag, rs in per_node.items():
        acc = defaultdict(lambda: {"sub": [], "rssi": []})
        for r in rs:
            b = int((r["t_capture"] - t0) / bin_s)
            a = np.asarray(r["csi"], dtype=np.float64)
            acc[b]["sub"].append(np.hypot(a[1::2], a[0::2]))
            acc[b]["rssi"].append(r["rssi"])
        # `var` butuh beberapa paket per bin untuk berarti; bin dengan sampel
        # terlalu sedikit dibuang, bukan diisi nilai yang menyesatkan.
        bins = sorted(b for b in acc if len(acc[b]["sub"]) >= min_pkt)
        amp, var = [], []
        for b in bins:
            A = np.array(acc[b]["sub"])          # (n_paket, n_subcarrier)
            active = A.mean(axis=0) > 1e-9       # buang guard band yang selalu 0
            amp.append(float(A[:, active].mean()))
            var.append(float(A[:, active].std(axis=0).mean()))
        out[tag] = {
            "bin": np.array(bins, dtype=np.int64),
            "t": np.array([b * bin_s for b in bins], dtype=np.float64),
            "amp": np.array(amp),
            "var": np.array(var),
            "rssi": np.array([np.mean(acc[b]["rssi"]) for b in bins]),
            "n_pkt": len(rs),
        }
    if n_skipped:
        print(f"  (dilewati {n_skipped} paket sig_len != {SIG_LEN})")
    return out, t0


def baseline_stats(sess, feat="amp"):
    """median dan MAD fitur per node dari capture ruangan kosong."""
    stats = {}
    for tag, d in sess.items():
        med = float(np.median(d[feat]))
        mad = float(np.median(np.abs(d[feat] - med)))
        # 1.4826 membuat MAD sebanding dengan std untuk data normal.
        sigma = 1.4826 * mad
        if sigma <= 0:
            # Board diam total sepanjang baseline; jangan bagi nol.
            sigma = float(np.std(d[feat])) or 1.0
            print(f"  ! node {tag}: MAD=0, pakai std={sigma:.3f}")
        stats[tag] = {"median": med, "sigma": sigma}
    return stats


def zscores(sess, base, tags, bin_ms, feat="amp"):
    """Susun matriks z-score (n_bin x n_node) pada sumbu bin yang sama.

    Hanya bin yang berisi SEMUA node yang dipakai. Bin yang bolong satu node
    tidak bisa dipakai untuk argmax antar node -- board yang datanya hilang akan
    tampak seperti board yang tidak terganggu.
    """
    common = None
    for tag in tags:
        s = set(sess[tag]["bin"].tolist())
        common = s if common is None else (common & s)
    common = np.array(sorted(common), dtype=np.int64)
    if common.size == 0:
        raise SystemExit(f"tidak ada bin yang berisi semua {len(tags)} node -- "
                         "cek apakah semua board hidup bersamaan")

    Z = np.zeros((common.size, len(tags)))
    for j, tag in enumerate(tags):
        d = sess[tag]
        idx = np.searchsorted(d["bin"], common)
        v = d[feat][idx]
        Z[:, j] = (v - base[tag]["median"]) / base[tag]["sigma"]
    t = common * (bin_ms / 1000.0)
    return t, Z, common


def learn_polarity(static_dir, base, tags, bin_ms, dwell_s, order,
                   feat="amp", min_pkt=1):
    """Tentukan tanda respons tiap board dari capture statik.

    Capture statik = berdiri diam `dwell_s` detik di tiap sudut, urut `order`.
    Untuk tiap board dilihat rata-rata z saat orang berada di sudut board itu
    dibanding saat berada di sudut lain. Kalau lebih tinggi -> scattering (+1),
    kalau lebih rendah -> shadowing (-1).
    """
    sess, _ = load_session(static_dir, bin_ms, min_pkt)
    missing = [t for t in tags if t not in sess]
    if missing:
        raise SystemExit(f"capture statik kehilangan node {missing}")
    t, Z, _ = zscores(sess, base, tags, bin_ms, feat)

    # Segmentasi waktu -> sudut. Sengaja memotong 20% di tiap ujung segmen:
    # detik-detik saat orang masih berjalan menuju/meninggalkan sudut bukan
    # sampel yang bersih.
    total = t[-1] - t[0]
    n_seg = len(order)
    seg_len = total / n_seg if dwell_s is None else dwell_s
    print(f"  segmen statik: {seg_len:.1f} s per sudut, urutan {' -> '.join(order)}")

    pol = {}
    means = np.full((n_seg, len(tags)), np.nan)
    for k, corner in enumerate(order):
        lo = t[0] + k * seg_len
        hi = lo + seg_len
        pad = 0.20 * seg_len
        m = (t >= lo + pad) & (t <= hi - pad)
        if m.sum() < 3:
            print(f"  ! segmen {corner} hanya {m.sum()} bin; polaritas tidak andal")
            continue
        means[k] = Z[m].mean(axis=0)

    for j, tag in enumerate(tags):
        k = order.index(tag) if tag in order else None
        if k is None or np.isnan(means[k, j]):
            pol[tag] = -1.0
            continue
        own = means[k, j]
        other = np.nanmean(np.delete(means[:, j], k))
        pol[tag] = 1.0 if own > other else -1.0
        kind = "scattering (naik)" if pol[tag] > 0 else "shadowing (turun)"
        print(f"  node {tag} ({CORNER_DESC.get(tag, '?')}): "
              f"z_sendiri={own:+.2f} z_lain={other:+.2f} -> {kind}")
    return pol, means


def markers_to_labels(markers_path, t, t0, order):
    """Ubah penanda sudut jadi label per bin dengan interpolasi antar penanda.

    Penanda dicatat SAAT MELEWATI sudut. Maka antara penanda ke-i dan ke-(i+1),
    orang bergerak dari sudut order[i] ke order[i+1]. Label kuadran diambil dari
    sudut TERDEKAT: paruh pertama segmen milik sudut asal, paruh kedua milik
    sudut tujuan. Ini memakai waktu nyata tiap lap, jadi tempo yang melenceng
    terkoreksi sendiri di tiap penanda alih-alih menumpuk.
    """
    import csv as _csv
    rows = []
    with open(markers_path, newline="", encoding="utf-8") as f:
        for r in _csv.DictReader(f):
            rows.append((float(r["host_time"]) - t0, r["corner"].strip().lower()))
    if len(rows) < 2:
        raise SystemExit(f"{markers_path}: butuh minimal 2 penanda")

    labels = np.full(t.size, "", dtype=object)
    for i in range(len(rows) - 1):
        ta, ca = rows[i]
        tb, cb = rows[i + 1]
        if tb <= ta:
            continue
        mid = 0.5 * (ta + tb)
        labels[(t >= ta) & (t < mid)] = ca
        labels[(t >= mid) & (t < tb)] = cb
    return labels, rows


def confusion(true_lab, pred_lab, tags):
    M = np.zeros((len(tags), len(tags)), dtype=int)
    idx = {t: i for i, t in enumerate(tags)}
    for a, b in zip(true_lab, pred_lab):
        if a in idx and b in idx:
            M[idx[a], idx[b]] += 1
    return M


def print_confusion(M, tags):
    print()
    print("  Confusion (baris = sebenarnya, kolom = prediksi)")
    head = "         " + "".join(f"{t:>8}" for t in tags) + "     akurasi"
    print(head)
    for i, t in enumerate(tags):
        row = M[i]
        acc = row[i] / row.sum() if row.sum() else 0.0
        print(f"  {t:>6} " + "".join(f"{v:>8d}" for v in row) + f"   {acc*100:6.1f}%")
    tot = M.sum()
    correct = np.trace(M)
    print(f"  {'TOTAL':>6} " + " " * (8 * len(tags)) + f"   {correct/tot*100 if tot else 0:6.1f}%")
    print(f"  (tebakan acak = {100.0/len(tags):.1f}%)")


def make_plot(path, t, Z, pol, tags, true_lab, pred_lab, markers):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"4b": "#d1495b", "bf": "#edae49", "38": "#00798c", "d0": "#66a182"}
    n = 3 if true_lab is not None else 2
    fig, axes = plt.subplots(n, 1, figsize=(14, 3.0 * n), sharex=True)

    ax = axes[0]
    for j, tag in enumerate(tags):
        ax.plot(t, Z[:, j], lw=0.8, color=colors.get(tag, None),
                label=f"{tag} ({CORNER_DESC.get(tag,'?')})")
    ax.axhline(0, color="k", lw=0.5, ls=":")
    ax.set_ylabel("z amplitudo\n(vs ruangan kosong)")
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    ax.set_title("Deviasi amplitudo CSI per board")

    ax = axes[1]
    S = Z * np.array([pol[t_] for t_ in tags])  # polaritas -> "makin besar makin dekat"
    for j, tag in enumerate(tags):
        ax.plot(t, S[:, j], lw=0.8, color=colors.get(tag, None), label=tag)
    ax.set_ylabel("skor terarah\n(besar = terganggu)")
    ax.legend(ncol=4, fontsize=8, loc="upper right")

    if true_lab is not None:
        ax = axes[2]
        yi = {tg: i for i, tg in enumerate(tags)}
        tv = np.array([yi.get(v, np.nan) for v in true_lab], dtype=float)
        pv = np.array([yi.get(v, np.nan) for v in pred_lab], dtype=float)
        ax.plot(t, tv, lw=2.5, color="0.75", label="sebenarnya (penanda)")
        ok = tv == pv
        ax.scatter(t[ok], pv[ok], s=4, color="#2a9d8f", label="prediksi benar")
        ax.scatter(t[~ok], pv[~ok], s=4, color="#e76f51", label="prediksi salah")
        ax.set_yticks(range(len(tags)))
        ax.set_yticklabels([f"{tg}\n{CORNER_DESC.get(tg,'')}" for tg in tags], fontsize=8)
        ax.set_ylabel("sudut")
        ax.legend(ncol=3, fontsize=8, loc="upper right")

    for a in axes:
        for tm, _c in (markers or []):
            a.axvline(tm, color="0.85", lw=0.6, zorder=0)
    axes[-1].set_xlabel("waktu (s)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    print(f"\nPlot -> {path}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("indir", help="folder capture yang dianalisis")
    ap.add_argument("--baseline", required=True,
                    help="folder capture ruangan KOSONG (wajib)")
    ap.add_argument("--static", help="folder capture statik, untuk menentukan polaritas")
    ap.add_argument("--static-mode", action="store_true",
                    help="perlakukan indir sendiri sebagai capture statik")
    ap.add_argument("--markers", help="markers.csv dari mark_events.py")
    ap.add_argument("--bin-ms", type=float, default=500.0,
                    help="lebar jendela dalam ms (default 500). Fitur `var` "
                         "butuh banyak paket per jendela, jadi jauh lebih lebar "
                         "daripada bin alignment 100 ms di csi_merge.py.")
    ap.add_argument("--feature", choices=["var", "amp"], default="var",
                    help="var = simpangan baku amplitudo antar paket dalam satu "
                         "jendela (DEFAULT, terbukti jauh lebih kuat); "
                         "amp = amplitudo rata-rata (nyaris tidak bereaksi pada "
                         "data 2026-09-09)")
    ap.add_argument("--min-pkt", type=int, default=8,
                    help="paket minimum per jendela agar `var` berarti (default 8)")
    ap.add_argument("--no-standardize", action="store_true",
                    help="jangan standardisasi tiap board pada capture yang "
                         "dianalisis. Standardisasi ON secara default: tanpa itu "
                         "board yang paling sensitif menang di semua kuadran.")
    ap.add_argument("--dwell-s", type=float, default=None,
                    help="detik per sudut di capture statik (default: bagi rata)")
    ap.add_argument("--order", default=",".join(CORNER_ORDER),
                    help=f"urutan sudut (default {','.join(CORNER_ORDER)})")
    ap.add_argument("--smooth", type=float, default=4.0,
                    help="lebar rata-rata bergerak dalam detik (default 1.0, 0=mati)")
    ap.add_argument("--plot", help="tulis PNG ringkasan")
    args = ap.parse_args()

    order = [c.strip().lower() for c in args.order.split(",") if c.strip()]

    print(f"Baseline (kosong): {args.baseline}")
    base_sess, _ = load_session(args.baseline, args.bin_ms, args.min_pkt)
    base = baseline_stats(base_sess, args.feature)
    tags = [t for t in order if t in base_sess]
    extra = sorted(set(base_sess) - set(tags))
    if extra:
        print(f"  ! node di luar --order, diabaikan: {extra}")
    if len(tags) < 2:
        raise SystemExit("butuh minimal 2 node yang cocok dengan --order")
    for tg in tags:
        print(f"  node {tg} ({CORNER_DESC.get(tg,'?')}): "
              f"{base_sess[tg]['n_pkt']} paket, "
              f"{args.feature} median={base[tg]['median']:.3f} "
              f"sigma={base[tg]['sigma']:.3f}")

    static_dir = args.indir if args.static_mode else args.static
    if static_dir and args.feature == "var" and not args.static_mode:
        # Estimasi polaritas dari capture statik hanya menambah derau di sini:
        # tanda `var` sudah pasti, dan capture statik 2026-09-09 ternyata
        # segmen waktunya tidak rapi sehingga tandanya sendiri tidak andal.
        print("\n! --static diabaikan untuk fitur `var`: polaritasnya sudah pasti +1.")
        static_dir = None
    if static_dir:
        print(f"\nPolaritas dari capture statik: {static_dir}")
        pol, _ = learn_polarity(static_dir, base, tags, args.bin_ms,
                                args.dwell_s, order, args.feature, args.min_pkt)
    elif args.feature == "var":
        # Fitur `var` tidak punya ambiguitas polaritas. Apa pun mekanismenya --
        # shadowing (menyerap) atau scattering (memantulkan) -- kehadiran orang
        # membuat kanal BERGERAK, jadi simpangan baku antar paket selalu NAIK.
        # Diverifikasi pada data 2026-09-09: var naik untuk keempat board, dan
        # memaksa polaritas negatif menjatuhkan akurasi ke 4.4%, jauh DI BAWAH
        # tebakan acak -- itulah tanda khas polaritas terbalik.
        pol = {t: +1.0 for t in tags}
        print("\nPolaritas: +1 semua board (fitur `var` selalu naik saat ada orang).")
    else:
        pol = {t: -1.0 for t in tags}
        print("\n! TANPA --static: polaritas amplitudo diasumsikan shadowing (turun).")
        print("  Kalau akurasi keluar di bawah tebakan acak, kemungkinan besar")
        print("  polaritasnya terbalik -- jalankan capture statik.")

    print(f"\nAnalisis: {args.indir}")
    sess, t0 = load_session(args.indir, args.bin_ms, args.min_pkt)
    miss = [t for t in tags if t not in sess]
    if miss:
        raise SystemExit(f"node hilang di {args.indir}: {miss}")
    t, Z, _ = zscores(sess, base, tags, args.bin_ms, args.feature)
    print(f"  {t.size} bin berisi semua {len(tags)} node, durasi {t[-1]-t[0]:.1f} s")

    # Skor terarah: setelah dikali polaritas, "lebih besar" selalu berarti
    # "board ini yang paling terganggu", apa pun arah fisikanya.
    S = Z * np.array([pol[tg] for tg in tags])

    # Standardisasi per board pada capture ini sendiri.
    #
    # Tiap board punya SENSITIVITAS berbeda, bukan cuma skala amplitudo berbeda:
    # pada data 2026-09-09 board 4b/d0 bereaksi ~z=3 di sudutnya sendiri sementara
    # 38 hanya ~z=0.5. argmax lintas board tanpa langkah ini otomatis dimenangkan
    # board yang paling sensitif di HAMPIR SEMUA kuadran -- 38 hanya menang 15%
    # di sudutnya sendiri. Setelah distandardisasi, yang dibandingkan adalah
    # "board mana yang paling menyimpang RELATIF TERHADAP kebiasaannya sendiri".
    # Efeknya besar: 48.6% -> 79.4% pada capture loc_walk.
    if not args.no_standardize:
        sd = S.std(axis=0)
        sd[sd == 0] = 1.0
        S = (S - S.mean(axis=0)) / sd

    if args.smooth > 0:
        w = max(1, int(round(args.smooth / (args.bin_ms / 1000.0))))
        if w > 1:
            k = np.ones(w) / w
            S = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, S)
            print(f"  rata-rata bergerak {w} bin ({args.smooth:.1f} s)")

    pred = np.array([tags[i] for i in np.argmax(S, axis=1)], dtype=object)

    print("\n  Sebaran prediksi:")
    for tg in tags:
        n = int((pred == tg).sum())
        print(f"    {tg} ({CORNER_DESC.get(tg,'?'):>12}): {n:6d} bin  "
              f"{100.0*n/pred.size:5.1f}%")

    true_lab = None
    markers = None
    if args.markers:
        true_lab, mrows = markers_to_labels(args.markers, t, t0, order)
        markers = mrows
        valid = np.array([v != "" for v in true_lab])
        if valid.sum() == 0:
            print("\n! penanda tidak beririsan dengan data; label diabaikan")
            true_lab = None
        else:
            print(f"\n  Label dari {len(mrows)} penanda, "
                  f"{valid.sum()}/{t.size} bin berlabel")
            M = confusion(true_lab[valid], pred[valid], tags)
            print_confusion(M, tags)
    elif args.static_mode:
        # Di mode statik urutan sudah diketahui dari --order dan durasi segmen.
        total = t[-1] - t[0]
        seg = total / len(order) if args.dwell_s is None else args.dwell_s
        true_lab = np.array([order[min(int((x - t[0]) / seg), len(order) - 1)]
                             for x in t], dtype=object)
        M = confusion(true_lab, pred, tags)
        print_confusion(M, tags)

    if args.plot:
        make_plot(args.plot, t, Z, pol, tags, true_lab, pred, markers)

    return 0


if __name__ == "__main__":
    sys.exit(main())
