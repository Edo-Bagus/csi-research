#!/usr/bin/env python3
"""Pemuat data counting: .bin multi-node + label okupansi -> array per-jendela.

Dipakai oleh `eda_people_count.ipynb`. Modul ini TIDAK memodelkan apa pun; dia
hanya membaca, menyelaraskan waktu, dan memberi label.

KENAPA read_bin DIIMPOR, BUKAN DISALIN
--------------------------------------
Format frame .bin tidak punya version field. Menyalin definisi struct ke sini
berarti mengundang mismatch yang gagal DIAM-DIAM saat firmware berubah: file
tetap terbaca, angkanya saja yang ngawur. Jadi satu-satunya definisi hidup di
tools/csi_merge.py dan dipakai ulang dari sana.

DUA DATASET = DUA RUANGAN BERBEDA
---------------------------------
`data-14-9` dan `data-15-9` direkam di RUANG KELAS YANG BERBEDA (dikonfirmasi
pengguna 2026-09-19), bukan dua sampel ruangan yang sama. Karena itu tiap dataset
punya objek `Dataset` sendiri dengan denah zona-board sendiri, dan fitur CSI dari
keduanya TIDAK BOLEH digabung jadi satu set latih -- itu mencampur efek ruangan
dengan efek jumlah orang. Klaim yang didukung adalah REPLIKASI: deteksi okupansi
berhasil di dua ruangan independen, dilaporkan per ruangan.

Denah zona berbeda antar dataset (C dan D tertukar), dan format frame .bin tidak
punya version field, jadi denah yang usang menghasilkan angka zona yang salah
TANPA pesan error. Karena itu denah ikut di objek Dataset, bukan konstanta global
yang diedit manual.

CATATAN DATA data-14-9 (dikonfirmasi pengguna 2026-09-14)
---------------------------------------------------------
1. Ada 16 orang di ruangan. Label absolut dipercaya apa adanya.
2. count_s10 adalah capture ruangan KOSONG (290 s, 4 board, nol event). Ini
   membuka normalize="empty" -- normalisasi per-board terhadap baseline kosong
   yang di ml_localization/features.py disebut wajib. Hanya ada SATU sesi kosong
   dan direkam ~1 jam setelah sesi lain, jadi perlakukan sebagai indikatif.
3. count_s01 board bf mati setelah 11 s; count_s02 tidak punya bf sama sekali.
   Keduanya efektif 3 board. Kolom `n_boards` dibawa terus supaya analisis
   lanjutan tidak diam-diam mencampur vektor fitur 3-board dan 4-board.
4. Penempatan board per zona ada di DS_14_9.zone_board (dikonfirmasi pengguna).
   Beda dari COUNTING_RUNBOOK.md -- lihat komentar di sana.
5. Zona B hampir selalu kosong di SEMUA sesi (rata-rata 0.0-0.6 orang). Analisis
   per zona karena itu praktis hanya bisa menyentuh A, C, dan D.

CATATAN DATA data-15-9 (dikonfirmasi pengguna 2026-09-19)
--------------------------------------------------------
1. RUANGAN LAIN, kelas ~1.5-2x lebih besar (plateau 52-72 orang). Jumlah pasti
   tidak tercatat; nilai plateau label dipakai apa adanya.
2. Denah zona: C=4b, D=38 -- TERTUKAR dibanding data-14-9.
3. Sembilan sesi, KEEMPAT board merekam di semua sesi dengan ukuran sebanding.
   Masalah board mati di count_s01/s02 TIDAK terulang di sini.
4. Label dicatat LIVE di semua sesi. Ledakan event di detik-detik awal adalah
   input manual yang MENYUSUL orang yang sudah masuk, bukan hitungan statis yang
   dimasukkan di t=0. Jadi label tetap berubah terhadap waktu -- jangan
   diringkas jadi satu N konstan per sesi. Yang tidak bisa dipercaya hanya
   TIMESTAMP DI DALAM ledakan awal; nilai akhirnya benar.
5. count_2_9 adalah capture nyaris kosong (90% span di total=0) -- padanan
   count_s10 sebagai baseline normalize="empty" untuk ruangan ini.
"""

import glob
import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .paths import DATA_RAW, TOOLS_DIR

# `read_bin` DIIMPOR dari tools/, bukan disalin (alasan di docstring modul).
# tools/ bukan paket ber-__init__.py, jadi satu-satunya cara mengimpornya adalah
# menambahkannya ke sys.path. Ini satu-satunya sys.path manipulation yang tersisa
# di proyek, dan sengaja dipusatkan di sini.
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from csi_merge import read_bin  # noqa: E402

SIG_LEN = 114        # v2: hanya frame ICMP echo reply dari router
ZONES = ["A", "B", "C", "D"]


@dataclass(frozen=True)
class Dataset:
    """Satu sesi pengumpulan di SATU ruangan: folder + denah zona + baseline.

    Denah zona ikut di sini, bukan jadi konstanta global, karena data-14-9 dan
    data-15-9 adalah ruangan berbeda dengan denah berbeda. Denah global yang
    diedit manual saat berpindah dataset akan diam-diam salah -- tidak ada
    version field di frame .bin yang bisa menangkapnya.
    """

    name: str
    dirname: str
    zone_board: dict
    empty_session: str | None
    note: str = ""

    @property
    def data_dir(self):
        """Folder data mentah dataset ini, di bawah data/raw/."""
        return str(DATA_RAW / self.dirname)

    @property
    def board_zone(self):
        return {b: z for z, b in self.zone_board.items()}

    def __str__(self):
        return self.name


# Penempatan board di tiap zona, dikonfirmasi pengguna 2026-09-14 dari
# pengukuran ruangan.
#
# CATATAN: ini BERBEDA dari denah di COUNTING_RUNBOOK.md, yang menulis
# A=38 dan C=d0 (tertukar). B dan D sama. Yang dipakai adalah angka pengguna --
# runbook itu rencana, pengguna yang mengukur ruangan sebenarnya. Data sendiri
# tidak bisa menengahi: korelasi board-zona terlalu lemah (|r| < 0.18) untuk
# membedakan kedua pemetaan.
DS_14_9 = Dataset(
    name="data-14-9",
    dirname="data-14-9",
    zone_board={"A": "d0", "B": "bf", "C": "38", "D": "4b"},
    empty_session="count_s10",
    note="ruangan 1; 16 orang; bf mati di s01, hilang di s02",
)

# Ruangan LAIN (dikonfirmasi pengguna 2026-09-19). C dan D tertukar dibanding
# ruangan 1. Kelas ~1.5-2x lebih besar.
DS_15_9 = Dataset(
    name="data-15-9",
    dirname="data-15-9",
    zone_board={"A": "d0", "B": "bf", "C": "4b", "D": "38"},
    empty_session="count_2_9",
    note="ruangan 2; kelas 52-72 orang; 4 board utuh di semua sesi",
)

DATASETS = {d.name: d for d in (DS_14_9, DS_15_9)}

# Default = ruangan 1, supaya notebook dan analisis lama tetap jalan tanpa diubah.
DEFAULT = DS_14_9

# Nama-nama lama, dipertahankan supaya call site yang sudah ada tidak putus.
DATA_DIR = DEFAULT.data_dir
ZONE_BOARD = DEFAULT.zone_board
BOARD_ZONE = DEFAULT.board_zone


def resolve(ds=None):
    """Terima Dataset, nama ("data-15-9"), path folder, atau None -> Dataset.

    Menerima path mentah supaya kode lama yang mengirim data_dir=... tetap jalan;
    path yang tidak dikenal dapat denah dataset default DENGAN peringatan, karena
    denah yang salah tidak menghasilkan error apa pun.
    """
    if ds is None:
        return DEFAULT
    if isinstance(ds, Dataset):
        return ds
    if isinstance(ds, str) and ds in DATASETS:
        return DATASETS[ds]
    base = os.path.basename(os.path.normpath(str(ds)))
    if base in DATASETS:
        return DATASETS[base]
    import warnings
    warnings.warn(
        f"dataset {ds!r} tidak dikenal; memakai denah zona {DEFAULT.name}. "
        "Kalau ini ruangan lain, denah zona kemungkinan SALAH dan tidak akan "
        "memunculkan error -- daftarkan di DATASETS.",
        stacklevel=2,
    )
    return Dataset(name=base, dirname=base,
                   zone_board=DEFAULT.zone_board,
                   empty_session=None, note="tidak terdaftar")


def node_tag(rec):
    """Nama pendek board ('4b','bf','38','d0') dari node_id.

    Ini node_id, BUKAN byte terakhir MAC: firmware mem-fold dua byte terakhir
    MAC (0x0b ^ 0x40 = 0x4b). Nama file .bin memakai konvensi yang sama.
    """
    return f"{rec['node_id']:02x}"


# ---------------------------------------------------------------- pembacaan

def read_node(path):
    """Satu .bin -> dict berisi amplitudo, rssi, waktu capture, tag board.

    Waktu capture direkonstruksi seperti csi_merge.py: jarak antar-paket diambil
    dari uptime_us (jam board, presisi) lalu seluruh sumbu digeser ke jam laptop
    dengan SATU offset = persentil-10 dari (host_time - uptime). Persentil bawah
    dipakai, bukan rata-rata, karena paket tercepat adalah yang paling sedikit
    tertunda antrean jaringan, jadi paling dekat ke offset sejati.
    """
    recs = [r for r in read_bin(path) if r["sig_len"] == SIG_LEN]
    if not recs:
        raise ValueError(f"tidak ada paket sig_len={SIG_LEN} di {path}")

    recs.sort(key=lambda r: r["uptime_us"])
    offs = sorted(r["host_time"] - r["uptime_us"] / 1e6 for r in recs)
    offset = offs[max(0, int(0.10 * len(offs)) - 1)]
    t = np.array([offset + r["uptime_us"] / 1e6 for r in recs])

    # csi mentah = int16 berpasangan (I,Q) per subcarrier -> amplitudo.
    raw = np.array([r["csi"] for r in recs], dtype=np.float64)
    iq = raw.reshape(len(recs), -1, 2)
    amp = np.sqrt((iq ** 2).sum(axis=-1))

    return {
        "tag": node_tag(recs[0]),
        "t": t,
        "amp": amp,                                     # (n_pkt, n_sub)
        "rssi": np.array([r["rssi"] for r in recs], dtype=np.float64),
        "host_time": np.array([r["host_time"] for r in recs]),
        "n_pkt": len(recs),
    }


def load_session(session, data_dir=None, ds=None):
    """Semua board satu sesi -> {tag: dict dari read_node}."""
    d = resolve(ds if ds is not None else data_dir)
    files = sorted(glob.glob(os.path.join(d.data_dir, session, "*.bin")))
    if not files:
        raise ValueError(f"tidak ada .bin di {d.name}/{session}")
    return {n["tag"]: n for n in (read_node(f) for f in files)}


def list_sessions(data_dir=None, ds=None):
    d = resolve(ds if ds is not None else data_dir)
    return sorted(x for x in os.listdir(d.data_dir)
                  if os.path.isdir(os.path.join(d.data_dir, x)))


# -------------------------------------------------------------------- label

def load_occupancy(session, data_dir=None, ds=None):
    """occupancy.csv -> DataFrame interval (t_start, t_end, A..D, total)."""
    d = resolve(ds if ds is not None else data_dir)
    path = os.path.join(d.data_dir, session, "occupancy.csv")
    df = pd.read_csv(path)
    for c in ZONES + ["total"]:
        df[c] = df[c].astype(int)
    return df


def load_events(session, data_dir=None, ds=None):
    d = resolve(ds if ds is not None else data_dir)
    path = os.path.join(d.data_dir, session, "occupancy_events.csv")
    return pd.read_csv(path)


def label_at(occ, times):
    """Label okupansi pada deretan waktu absolut.

    Dijoin lewat host_time (waktu absolut), BUKAN t_rel: t_rel dihitung dari
    saat pencatat label dijalankan, yang tidak sama dengan saat kolektor mulai.
    Menjoin lewat t_rel menggeser seluruh label beberapa detik tanpa error.

    Label adalah interval [t_start, t_end), jadi searchsorted di t_start.
    Waktu di luar rentang pencatat -> NaN (dibuang belakangan, bukan diisi 0:
    "tidak tercatat" bukan berarti "kosong").
    """
    times = np.asarray(times, dtype=float)
    starts = occ["t_start"].to_numpy()
    idx = np.searchsorted(starts, times, side="right") - 1
    valid = (idx >= 0) & (times < occ["t_end"].to_numpy()[-1])

    out = {}
    for col in ZONES + ["total"]:
        v = np.full(len(times), np.nan)
        vals = occ[col].to_numpy()
        v[valid] = vals[idx[valid]]
        out[col] = v
    return pd.DataFrame(out)


# ------------------------------------------------------------------ jendela

STATS = ["amp_mean", "amp_std", "sub_var", "sub_std_spatial",
         "rssi_mean", "rssi_std"]


def window_features(session, win_s=2.0, hop_s=1.0, normalize="none",
                    min_span_frac=0.5, data_dir=None, ds=None):
    """Ringkas tiap board jadi statistik per jendela waktu, lalu beri label.

    normalize:
      "none"    -- nilai apa adanya. Perbedaan level antar board ikut terbawa.
      "session" -- standardisasi robust (median/MAD) per board per SESI.
      "empty"   -- relatif terhadap capture ruangan KOSONG (count_s10).

    Kenapa tiga pilihan, dan kapan pakai yang mana:

    "session" membuang perbedaan antar board, TAPI juga membuang level yang
    mungkin mengkodekan jumlah orang -- okupansi hampir konstan di tiap sesi,
    jadi "median sesi" sebagian besar ADALAH kondisi berpenghuni.

    "empty" adalah yang sebenarnya diinginkan, dan baru mungkin sejak count_s10
    (ruangan kosong 290 detik) ada. Ini yang disebut wajib di
    ml_localization/features.py: tiap fitur dinyatakan relatif terhadap statistik
    board ITU SENDIRI saat ruangan kosong, sehingga board yang kebetulan dekat
    router tidak otomatis menang.

    PERINGATAN soal "empty": hanya ada SATU sesi kosong, direkam ~1 jam setelah
    sesi lain. Jadi acuan ini mencampur "kosong" dengan "kondisi kanal pukul
    15:19". Sampai ada beberapa sesi kosong di waktu berbeda, perlakukan hasil
    bernormalisasi "empty" sebagai indikatif, bukan final.
    """
    d = resolve(ds if ds is not None else data_dir)
    nodes = load_session(session, ds=d)
    occ = load_occupancy(session, ds=d)

    # Board yang mati di tengah sesi harus DIBUANG, bukan dipakai memotong
    # rentang waktu sesi. Di count_s01 board bf berhenti setelah 11 detik dari
    # 293 detik; irisan naif "semua board hidup" menyisakan 9 jendela saja dan
    # membuang 97% sesi tanpa satu pun pesan error.
    span = {tag: n["t"].max() - n["t"].min() for tag, n in nodes.items()}
    longest = max(span.values())
    dropped = [t for t, s in span.items() if s < min_span_frac * longest]
    for t in dropped:
        del nodes[t]
    if not nodes:
        raise ValueError(f"{session}: tidak ada board yang merekam cukup lama")

    t_lo = max(n["t"].min() for n in nodes.values())
    t_hi = min(n["t"].max() for n in nodes.values())
    starts = np.arange(t_lo, t_hi - win_s, hop_s)

    tags = sorted(nodes)
    rows = []
    for w0 in starts:
        w1 = w0 + win_s
        row = {"session": session, "t_start": w0, "t_mid": w0 + win_s / 2}
        ok = True
        for tag in tags:
            n = nodes[tag]
            m = (n["t"] >= w0) & (n["t"] < w1)
            k = int(m.sum())
            row[f"{tag}_npkt"] = k
            if k < 5:                     # jendela terlalu kosong untuk statistik
                ok = False
                continue
            a = n["amp"][m]               # (k, n_sub)
            per_pkt = a.mean(axis=1)      # amplitudo rata-rata tiap paket
            row[f"{tag}_amp_mean"] = per_pkt.mean()
            row[f"{tag}_amp_std"] = per_pkt.std()
            # Variance per subcarrier lalu dirata-rata: catatan riset sebelumnya
            # menemukan sebaran (variance) jauh lebih informatif daripada level
            # rata-rata -- 79% vs 36% untuk lokalisasi.
            row[f"{tag}_sub_var"] = a.var(axis=0).mean()
            row[f"{tag}_sub_std_spatial"] = a.mean(axis=0).std()
            row[f"{tag}_rssi_mean"] = n["rssi"][m].mean()
            row[f"{tag}_rssi_std"] = n["rssi"][m].std()
        row["_ok"] = ok
        rows.append(row)

    df = pd.DataFrame(rows)
    lab = label_at(occ, df["t_mid"].to_numpy())
    df = pd.concat([df, lab], axis=1)
    df["dataset"] = d.name
    df["n_boards"] = len(tags)
    df["boards"] = ",".join(tags)
    df["dropped_boards"] = ",".join(sorted(dropped))

    if normalize == "session":
        for tag in tags:
            for stat in STATS:
                c = f"{tag}_{stat}"
                if c not in df:
                    continue
                v = df[c].to_numpy(dtype=float)
                med = np.nanmedian(v)
                mad = np.nanmedian(np.abs(v - med))
                # MAD=0 terjadi kalau kanal benar-benar diam; jangan bagi nol.
                df[c] = (v - med) / (1.4826 * mad) if mad > 0 else v - med
    elif normalize == "empty":
        base = empty_baseline(win_s=win_s, hop_s=hop_s, ds=d)
        for tag in tags:
            for stat in STATS:
                c = f"{tag}_{stat}"
                if c not in df or c not in base:
                    continue
                med, mad = base[c]
                df[c] = ((df[c].to_numpy(dtype=float) - med) / mad
                         if mad > 0 else df[c].to_numpy(dtype=float) - med)
    elif normalize != "none":
        raise ValueError(f"normalize tidak dikenal: {normalize!r}")
    return df


EMPTY_SESSION = DEFAULT.empty_session   # nama lama; per-dataset ada di ds.empty_session
_BASELINE_CACHE = {}


def empty_baseline(win_s=2.0, hop_s=1.0, data_dir=None, ds=None):
    """Statistik tiap board saat ruangan KOSONG -> {kolom: (median, skala)}.

    Dipakai oleh normalize="empty". Median/MAD, bukan mean/std, supaya satu-dua
    jendela aneh (mis. seseorang lewat di depan pintu) tidak menggeser acuan.
    """
    d = resolve(ds if ds is not None else data_dir)
    if d.empty_session is None:
        raise ValueError(
            f"{d.name}: tidak ada sesi ruangan kosong terdaftar, "
            'normalize="empty" tidak bisa dipakai')
    key = (win_s, hop_s, d.name)
    if key in _BASELINE_CACHE:
        return _BASELINE_CACHE[key]
    e = window_features(d.empty_session, win_s=win_s, hop_s=hop_s,
                        normalize="none", ds=d)
    out = {}
    for c in e.columns:
        if not any(c.endswith("_" + s) for s in STATS):
            continue
        v = e[c].to_numpy(dtype=float)
        med = np.nanmedian(v)
        out[c] = (med, 1.4826 * np.nanmedian(np.abs(v - med)))
    _BASELINE_CACHE[key] = out
    return out
