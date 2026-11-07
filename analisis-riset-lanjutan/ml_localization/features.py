#!/usr/bin/env python3
"""Ekstraksi fitur per-jendela dari capture CSI multi-node, untuk model ML.

Modul ini menyiapkan matriks (n_window x n_feature) plus label sudut, siap
dipakai scikit-learn. Notebook `localization_ml.ipynb` memakainya; skrip ini
tidak melakukan pemodelan apa pun.

BEDA DENGAN tools/localize_baseline.py
--------------------------------------
`localize_baseline.py` menghitung SATU angka per board per jendela (variance
amplitudo) lalu memilih board pemenang lewat argmax -- itu aturan tangan, bukan
model terlatih, dan itulah baseline yang harus dikalahkan (79.4%).

Di sini tiap board menyumbang PULUHAN fitur: statistik amplitudo, ringkasan per
pita subcarrier, statistik RSSI, dan turunan waktunya. Catatan riset sebelumnya
menemukan std RSSI kira-kira menggandakan diri saat ada orang, jadi RSSI ikut
masuk, bukan hanya CSI.

YANG TIDAK BOLEH DILUPAKAN
--------------------------
1. Normalisasi per board terhadap capture KOSONG itu wajib, bukan kosmetik.
   Sensitivitas board berbeda jauh; tanpa itu board yang paling dekat router
   selalu menang. Semua fitur di sini dinyatakan relatif terhadap statistik
   board itu sendiri saat ruangan kosong.
2. Jendela yang berdekatan sangat berkorelasi. JANGAN pernah membagi
   train/test secara acak per jendela -- pakai `lap` sebagai grup.
3. `loc_static` TIDAK dipakai: penandaan waktunya salah dan tidak ada
   markers.csv, jadi labelnya tidak bisa dipercaya. Polaritas juga tidak
   diperlukan untuk fitur berbasis sebaran (variance selalu naik saat ada
   orang), jadi tidak ada yang hilang.
"""

import glob
import os
import sys
from collections import defaultdict

import numpy as np

# Pembaca frame .bin sengaja dipakai ulang dari tools/csi_merge.py: format frame
# tidak punya version field, jadi menyalin definisi struct ke sini berarti
# mengundang mismatch yang gagal diam-diam saat firmware berubah.
_TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
sys.path.insert(0, os.path.abspath(_TOOLS))
from csi_merge import read_bin  # noqa: E402

SIG_LEN = 114          # v2: hanya frame ICMP echo reply
N_BAND = 8             # jumlah pita subcarrier yang diringkas per board

# Urutan jalan yang disepakati: 4b -> bf -> 38 -> d0, lalu kembali ke 4b.
CORNER_ORDER = ["4b", "bf", "38", "d0"]
CORNER_DESC = {
    "4b": "kanan-bawah",
    "bf": "kanan-atas",
    "38": "kiri-atas",
    "d0": "kiri-bawah",
}
# Sudut geometris tiap sudut ruangan dilihat dari router (derajat, CCW dari
# sumbu +x). Dipakai untuk mengukur apakah kesalahan jatuh ke sudut TETANGGA
# (wajar) atau sudut SEBERANG (mencurigakan).
CORNER_ANGLE = {"4b": -45.0, "bf": 45.0, "38": 135.0, "d0": 225.0}


def node_tag(rec):
    """Nama pendek board ('4b','bf','38','d0') dari field node_id.

    Ini node_id, BUKAN byte terakhir MAC: firmware mem-fold dua byte terakhir
    MAC, jadi 588c:8142:0b40 -> 0x0b ^ 0x40 = 0x4b. Nama file .bin memakai
    konvensi yang sama sehingga label di sini cocok dengan nama file.
    """
    return f"{rec['node_id']:02x}"


def _read_node_packets(path):
    """Baca satu .bin -> (amplitudo per paket, rssi, waktu capture, tag)."""
    recs = [r for r in read_bin(path) if r["sig_len"] == SIG_LEN]
    if not recs:
        raise SystemExit(f"tidak ada paket sig_len={SIG_LEN} di {path}")

    # Rekonstruksi waktu identik dengan csi_merge.py / localize_baseline.py:
    # jam board yang presisi digeser ke jam laptop yang bisa dibandingkan antar
    # node, satu offset per node dari persentil-10 supaya tidak tertarik ekor.
    recs.sort(key=lambda r: r["uptime_us"])
    deltas = sorted(r["host_time"] - r["uptime_us"] / 1e6 for r in recs)
    offset = deltas[max(0, int(0.10 * len(deltas)) - 1)]

    t = np.array([r["uptime_us"] / 1e6 + offset for r in recs])
    rssi = np.array([r["rssi"] for r in recs], dtype=np.float64)

    raw = np.asarray([r["csi"] for r in recs], dtype=np.float64)
    # Buffer CSI = pasangan (imag, real) int16 berselang-seling.
    amp = np.hypot(raw[:, 1::2], raw[:, 0::2])   # (n_paket, n_subcarrier)

    return amp, rssi, t, node_tag(recs[0])


def load_capture(indir, verbose=True):
    """Baca semua .bin di satu folder -> dict per board + t0 bersama."""
    files = sorted(glob.glob(os.path.join(indir, "*.bin")))
    if not files:
        raise SystemExit(f"tidak ada .bin di {indir}")

    nodes = {}
    for path in files:
        amp, rssi, t, tag = _read_node_packets(path)
        nodes[tag] = {"amp": amp, "rssi": rssi, "t": t}
        if verbose:
            dur = t.max() - t.min()
            print(f"  node {tag}: {len(t):6d} paket, {dur:6.1f} s, "
                  f"{len(t)/dur:5.1f} Hz")

    t0 = min(d["t"].min() for d in nodes.values())
    for d in nodes.values():
        d["t"] = d["t"] - t0
    return nodes, t0


def active_subcarrier_mask(nodes):
    """Subcarrier yang bukan guard band, disepakati LINTAS board.

    Maskernya harus sama untuk semua board: kalau tiap board memakai himpunan
    subcarrier sendiri, fitur pita ke-k board A dan board B tidak lagi mengukur
    hal yang sama, dan model belajar dari perbedaan indeks, bukan dari fisika.
    """
    mask = None
    for d in nodes.values():
        m = d["amp"].mean(axis=0) > 1e-9
        mask = m if mask is None else (mask & m)
    return mask


def _window_stats(amp_w, rssi_w, mask, n_band=N_BAND):
    """Statistik satu jendela untuk satu board -> (vektor fitur, nama).

    amp_w: (n_paket_dalam_jendela, n_subcarrier)
    """
    A = amp_w[:, mask]                     # (n_pkt, n_sub_aktif)
    per_pkt = A.mean(axis=1)               # amplitudo rata-rata tiap paket
    per_sub_std = A.std(axis=0)            # variabilitas tiap subcarrier

    feats, names = [], []

    # --- amplitudo: level dan sebaran -------------------------------------
    # Catatan riset: MEAN hampir buta (36.5%), SEBARAN yang membawa sinyal.
    # Keduanya tetap disertakan supaya model sendiri yang memutuskan.
    feats += [per_pkt.mean(), per_pkt.std(), per_sub_std.mean(),
              per_sub_std.std(), per_sub_std.max()]
    names += ["amp_mean", "amp_tstd", "sub_std_mean", "sub_std_std",
              "sub_std_max"]

    # MAD antar paket: sebaran yang tahan terhadap satu paket rusak.
    med = np.median(per_pkt)
    feats += [float(np.median(np.abs(per_pkt - med)))]
    names += ["amp_mad"]

    # Rentang antar-persentil: gerakan besar tanpa terpengaruh ekor ekstrem.
    q10, q90 = np.percentile(per_pkt, [10, 90])
    feats += [float(q90 - q10)]
    names += ["amp_iqr80"]

    # --- ringkasan per pita subcarrier -------------------------------------
    # Fading selektif frekuensi: badan orang tidak mengubah semua subcarrier
    # dengan cara yang sama. Diringkas jadi n_band pita supaya jumlah fitur
    # tetap masuk akal untuk 8 lap data.
    bands = np.array_split(np.arange(A.shape[1]), n_band)
    for k, idx in enumerate(bands):
        feats += [float(A[:, idx].std(axis=0).mean())]
        names += [f"band{k}_std"]

    # --- korelasi waktu ----------------------------------------------------
    # Seberapa cepat kanal berubah di dalam jendela. Orang bergerak membuat
    # paket berurutan makin tidak mirip.
    if A.shape[0] >= 3:
        d1 = np.abs(np.diff(per_pkt)).mean()
        # korelasi lag-1 dari deret amplitudo per paket
        x = per_pkt - per_pkt.mean()
        denom = (x * x).sum()
        ac1 = float((x[:-1] * x[1:]).sum() / denom) if denom > 0 else 0.0
    else:
        d1, ac1 = 0.0, 0.0
    feats += [float(d1), ac1]
    names += ["amp_absdiff", "amp_ac1"]

    # --- RSSI --------------------------------------------------------------
    # Catatan riset: std RSSI kira-kira menggandakan diri saat ada orang
    # (0.4 -> 0.8..1.2 dBm). Murah dan informatif, jadi wajib ikut.
    feats += [float(rssi_w.mean()), float(rssi_w.std()),
              float(rssi_w.max() - rssi_w.min())]
    names += ["rssi_mean", "rssi_std", "rssi_range"]

    return np.array(feats, dtype=np.float64), names


def extract_windows(nodes, tags, mask, win_s=0.5, min_pkt=8, n_band=N_BAND):
    """Potong capture jadi jendela tetap -> (t, X_per_board, nama_fitur).

    Hanya jendela yang terisi cukup paket di SEMUA board yang dipakai. Jendela
    yang bolong satu board tidak bisa dipakai untuk perbandingan antar board:
    board yang datanya hilang akan tampak seperti board yang tidak terganggu.
    """
    t_end = min(d["t"].max() for d in nodes.values())
    n_win = int(t_end // win_s)

    rows, times = [], []
    names_out = None
    for w in range(n_win):
        lo, hi = w * win_s, (w + 1) * win_s
        per_board, ok = [], True
        for tag in tags:
            d = nodes[tag]
            i0, i1 = np.searchsorted(d["t"], [lo, hi])
            if i1 - i0 < min_pkt:
                ok = False
                break
            f, names = _window_stats(d["amp"][i0:i1], d["rssi"][i0:i1],
                                     mask, n_band)
            per_board.append(f)
            names_out = names
        if ok:
            rows.append(np.concatenate(per_board))
            times.append(lo + win_s / 2.0)

    if not rows:
        raise SystemExit("tidak ada jendela yang terisi di semua board -- "
                         "cek apakah semua board hidup bersamaan")

    X = np.vstack(rows)
    t = np.array(times)
    feat_names = [f"{tag}_{n}" for tag in tags for n in names_out]
    return t, X, feat_names


def baseline_normalize(X_walk, X_base, feat_names, eps=1e-9):
    """Nyatakan tiap fitur relatif terhadap capture ruangan KOSONG.

    z = (x - median_kosong) / (1.4826 * MAD_kosong)

    MAD dipakai, bukan std: baseline cuma 2 menit, dan satu lonjakan
    interferensi sudah cukup untuk menggelembungkan std lalu mengecilkan semua
    z sesudahnya. Faktor 1.4826 membuat MAD sebanding dengan std pada data
    normal, jadi angka z bisa dibaca sebagai "berapa sigma".

    Ini langkah yang membuat board bisa dibandingkan satu sama lain. Tanpa ini
    perbedaan sensitivitas antar board mendominasi segalanya.
    """
    med = np.median(X_base, axis=0)
    mad = np.median(np.abs(X_base - med), axis=0)
    sigma = 1.4826 * mad

    # Fitur yang benar-benar konstan saat ruangan kosong: jangan bagi nol.
    dead = sigma <= eps
    if dead.any():
        fallback = X_base.std(axis=0)
        sigma = np.where(dead, np.where(fallback > eps, fallback, 1.0), sigma)

    return (X_walk - med) / sigma, med, sigma


def add_context_features(t, Z, tags, n_per_board, win_s, base_names=None):
    """Tambah fitur yang hanya ada di tingkat SISTEM, bukan per board.

    Dua kelompok:

    - PERINGKAT antar board pada fitur sebaran utama. Yang menentukan arah
      bukan nilai absolut satu board, melainkan board mana yang paling
      terganggu relatif terhadap yang lain. Aturan argmax lama pada dasarnya
      hanya memakai peringkat teratas ini; di sini seluruh peringkat diberikan
      ke model.
    - SELISIH WAKTU (delta) tiap fitur board. Orang yang berjalan membuat
      gangguan datang lalu pergi; arah perubahan membedakan "sedang mendekat"
      dari "sedang menjauh", yang tidak terlihat dari nilai sesaat.
    """
    extra, names = [], []

    # Kolom 'sub_std_mean' tiap board: proksi variance yang dipakai baseline
    # lama, jadi peringkatnya langsung sebanding dengan aturan argmax.
    # Dicari lewat NAMA, bukan indeks tetap: menambah satu fitur di
    # _window_stats akan menggeser indeks dan kesalahannya tidak menimbulkan
    # error, hanya hasil yang salah diam-diam.
    if base_names is None:
        key = 2   # urutan lama; hanya dipakai kalau nama tidak tersedia
    else:
        block = base_names[:n_per_board]
        key = next(i for i, n in enumerate(block) if n.endswith("sub_std_mean"))
    cols = [j * n_per_board + key for j in range(len(tags))]
    V = Z[:, cols]

    # softmax-share: proporsi "gangguan" tiap board pada jendela itu
    Vp = V - V.min(axis=1, keepdims=True)
    share = Vp / (Vp.sum(axis=1, keepdims=True) + 1e-9)
    extra.append(share)
    names += [f"share_{tag}" for tag in tags]

    # peringkat (0 = paling kecil, n-1 = paling besar)
    order = np.argsort(np.argsort(V, axis=1), axis=1).astype(float)
    extra.append(order)
    names += [f"rank_{tag}" for tag in tags]

    # selisih board teratas vs kedua: seberapa yakin pemenangnya
    Vs = np.sort(V, axis=1)
    extra.append((Vs[:, -1] - Vs[:, -2]).reshape(-1, 1))
    names += ["top1_minus_top2"]

    # delta waktu seluruh fitur board (turunan kasar, satu jendela ke belakang)
    dZ = np.vstack([np.zeros((1, Z.shape[1])), np.diff(Z, axis=0)])
    extra.append(dZ)
    names += [f"d_{tag}_{k}" for tag in tags for k in range(n_per_board)]

    return np.hstack([Z] + extra), names


def smooth_time(X, t, tau_s):
    """Rata-rata bergerak terpusat selebar tau_s detik.

    Gangguan satu jendela (500 ms) jauh lebih pendek daripada waktu orang
    melintasi satu kuadran (~7 detik), jadi penghalusan menaikkan rasio
    sinyal-derau. Tapi penghalusan yang terlalu lebar akan mengaburkan
    transisi sudut yang justru ingin dideteksi -- catatan riset menemukan
    akurasi memuncak di 6-8 s lalu runtuh setelah 10 s.

    PENTING: ini memakai jendela terpusat, jadi ia MELIHAT MASA DEPAN. Untuk
    analisis offline (skripsi) itu sah dan sengaja dipilih agar sebanding
    dengan baseline lama yang juga terpusat. Untuk sistem real-time, ganti
    dengan rata-rata kausal (hanya masa lalu).
    """
    if tau_s <= 0:
        return X
    dt = np.median(np.diff(t))
    k = max(1, int(round(tau_s / dt)))
    if k % 2 == 0:
        k += 1
    pad = k // 2
    Xp = np.pad(X, ((pad, pad), (0, 0)), mode="edge")
    ker = np.ones(k) / k
    return np.column_stack([np.convolve(Xp[:, j], ker, mode="valid")
                            for j in range(X.shape[1])])


def load_markers(path):
    """Baca markers.csv -> (t_rel, corner, lap) sebagai array."""
    import csv as _csv
    t, corner, lap = [], [], []
    with open(path, newline="") as f:
        for row in _csv.DictReader(f):
            t.append(float(row["t_rel"]))
            corner.append(row["corner"])
            lap.append(int(row["lap"]))
    return np.array(t), np.array(corner), np.array(lap, dtype=int)


def label_windows(t_win, t_mark, corner_mark, lap_mark):
    """Beri label sudut ke tiap jendela: penanda TERDEKAT dalam waktu.

    Penanda mencatat saat orang MELEWATI sebuah sudut, bukan rentang waktu ia
    berada di sana. Jadi label "sudut terdekat" berarti: kuadran yang sedang
    dilalui. Batas antar kuadran memang kabur -- dan itu jujur, karena
    geometrinya pun kabur di sana. Definisi ini sama dengan yang dipakai
    localize_baseline.py, sehingga angkanya bisa dibandingkan langsung.

    Jendela di luar rentang penanda dibuang: sebelum penanda pertama dan
    sesudah penanda terakhir, posisi orang tidak diketahui.
    """
    lo, hi = t_mark.min(), t_mark.max()
    keep = (t_win >= lo) & (t_win <= hi)

    idx = np.abs(t_win[:, None] - t_mark[None, :]).argmin(axis=1)
    y = corner_mark[idx]
    lap = lap_mark[idx]
    return y, lap, keep


def angular_error(y_true, y_pred):
    """Selisih sudut (derajat, 0..180) antara dua label sudut ruangan.

    Dipakai untuk memisahkan kesalahan ke sudut TETANGGA (90 derajat, wajar
    untuk penaksir bearing) dari kesalahan ke sudut SEBERANG (180 derajat,
    tanda ada yang salah).
    """
    a = np.array([CORNER_ANGLE[c] for c in y_true])
    b = np.array([CORNER_ANGLE[c] for c in y_pred])
    d = np.abs((a - b + 180.0) % 360.0 - 180.0)
    return d


def build_dataset(walk_dir, base_dir, markers_path, win_s=0.5, min_pkt=8,
                  smooth_s=4.0, tags=None, n_band=N_BAND, verbose=True,
                  merge_last_lap=True):
    """Pipeline lengkap: folder capture -> dict berisi X, y, lap, t, nama.

    Urutannya penting: normalisasi baseline dulu (membuat board sebanding),
    LALU fitur konteks (peringkat antar board hanya berarti setelah sebanding),
    LALU penghalusan, dan terakhir pelabelan.

    Mengembalikan dict, bukan tuple panjang, supaya pemanggil tidak perlu
    menebak apa pun -- khususnya `n_per_board`, yang dibutuhkan untuk menemukan
    kolom fitur tertentu dan berubah kalau `n_band` diubah. Menebak angka itu
    di notebook pernah membuat perbandingan baseline salah kolom tanpa error.
    """
    if verbose:
        print(f"[baseline] {base_dir}")
    base_nodes, _ = load_capture(base_dir, verbose)
    if verbose:
        print(f"[walk] {walk_dir}")
    walk_nodes, _ = load_capture(walk_dir, verbose)

    if tags is None:
        tags = [c for c in CORNER_ORDER if c in walk_nodes]
    missing = [c for c in tags if c not in base_nodes]
    if missing:
        raise SystemExit(f"baseline kehilangan board {missing}")

    # Masker subcarrier ditentukan dari KEDUA capture supaya kolom fitur
    # merujuk ke subcarrier yang sama di baseline dan di walk.
    mask = active_subcarrier_mask(base_nodes) & active_subcarrier_mask(walk_nodes)
    if verbose:
        print(f"  subcarrier aktif: {mask.sum()} dari {mask.size}")

    t_b, Xb, _ = extract_windows(base_nodes, tags, mask, win_s, min_pkt, n_band)
    t_w, Xw, names = extract_windows(walk_nodes, tags, mask, win_s, min_pkt,
                                     n_band)
    n_per_board = len(names) // len(tags)

    Z, med, sigma = baseline_normalize(Xw, Xb, names)
    Z, ctx_names = add_context_features(t_w, Z, tags, n_per_board, win_s,
                                        base_names=names)
    all_names = names + ctx_names

    Zs = smooth_time(Z, t_w, smooth_s)

    t_m, c_m, l_m = load_markers(markers_path)
    y, lap, keep = label_windows(t_w, t_m, c_m, l_m)
    lap = lap[keep]

    # Penanda terakhir menutup lap ke-8 sekaligus membuka "lap 9" yang hanya
    # berisi beberapa jendela. Grup sekecil itu bukan lipatan CV yang berarti,
    # jadi digabung ke lap sebelumnya agar tersisa 8 lap utuh.
    if merge_last_lap and lap.size:
        laps, counts = np.unique(lap, return_counts=True)
        if len(laps) > 1 and counts[-1] < 0.3 * np.median(counts[:-1]):
            lap = np.where(lap == laps[-1], laps[-2], lap)

    if verbose:
        print(f"  jendela: {len(t_w)} total, {keep.sum()} berlabel, "
              f"{Zs.shape[1]} fitur, {len(np.unique(lap))} lap")

    return {
        "X": Zs[keep],
        "y": y[keep],
        "lap": lap,
        "t": t_w[keep],
        "names": all_names,
        "tags": tags,
        # Blok fitur per board berukuran tetap dan berurutan sesuai `tags`,
        # jadi kolom fitur ke-k board ke-j ada di j * n_per_board + k.
        "n_per_board": n_per_board,
        "win_s": win_s,
        "smooth_s": smooth_s,
    }


def build_dataset_cached(walk_dir, base_dir, markers_path, cache_dir="cache",
                         verbose=True, **kw):
    """`build_dataset` dengan hasil disimpan ke .npz.

    Membaca ulang ~83 MB .bin memakan waktu puluhan detik, dan di notebook itu
    terjadi tiap kali kernel di-restart. Kunci cache mencakup semua parameter
    yang mengubah isi fitur, jadi mengubah `win_s` atau `smooth_s` otomatis
    menghasilkan cache baru dan tidak pernah memakai yang basi.
    """
    import hashlib
    import json

    key = json.dumps({"walk": os.path.abspath(walk_dir),
                      "base": os.path.abspath(base_dir),
                      "mark": os.path.abspath(markers_path),
                      **{k: kw[k] for k in sorted(kw)}}, sort_keys=True)
    # Waktu modifikasi .bin ikut masuk kunci: kalau capture diganti, cache lama
    # tidak boleh terpakai diam-diam.
    for d in (walk_dir, base_dir):
        for f in sorted(glob.glob(os.path.join(d, "*.bin"))):
            key += f"|{os.path.basename(f)}:{os.path.getmtime(f):.0f}"
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    path = os.path.join(cache_dir, f"features_{h}.npz")

    if os.path.exists(path):
        z = np.load(path, allow_pickle=True)
        if verbose:
            print(f"[cache] {path}")
        return {k: (z[k].tolist() if z[k].dtype == object or k in
                    ("names", "tags", "n_per_board", "win_s", "smooth_s")
                    else z[k]) for k in z.files}

    ds = build_dataset(walk_dir, base_dir, markers_path, verbose=verbose, **kw)
    os.makedirs(cache_dir, exist_ok=True)
    np.savez_compressed(path, **{k: np.array(v, dtype=object)
                                 if isinstance(v, list) else np.array(v)
                                 for k, v in ds.items()})
    if verbose:
        print(f"[cache] disimpan ke {path}")
    return ds


def board_feature_cols(ds, feat_name):
    """Kolom fitur `feat_name` untuk semua board, urut sesuai ds['tags'].

    Dipakai untuk mereproduksi aturan argmax lama dan untuk plot per board.
    Mencari lewat nama, bukan lewat indeks yang ditebak, supaya perubahan
    jumlah pita subcarrier tidak diam-diam menggeser kolom yang dibaca.
    """
    cols = []
    for j, tag in enumerate(ds["tags"]):
        want = f"{tag}_{feat_name}"
        k = ds["names"].index(want, j * ds["n_per_board"])
        cols.append(k)
    return cols
