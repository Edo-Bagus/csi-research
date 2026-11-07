# -*- coding: utf-8 -*-
# Definisi sel notebook. Dijalankan oleh build_nb.py; md() dan code() dari sana.

md(r"""
# EDA — People Counting dari CSI Multi-Node (`data-14-9`)

Notebook ini memeriksa data capture 14 September 2026: **10 sesi**, 4 board ESP32
di sudut ruangan, router di tengah, **16 orang** di dalam ruangan.

> **Revisi setelah penambahan `count_s09` dan `count_s10`.** Versi pertama
> notebook ini ditulis saat baru ada 8 sesi dan TIDAK ADA capture ruangan kosong.
> `count_s10` adalah ruangan kosong selama 290 detik — ini mengubah kesimpulan
> secara substansial, karena akhirnya ada acuan untuk membandingkan "ada orang"
> lawan "tidak ada orang". Bagian 4b berisi analisis yang sebelumnya mustahil.

## Batasan yang harus dibaca sebelum menafsirkan angka mana pun

1. **Okupansi hampir konstan di dalam tiap sesi berpenghuni.** Tiap sesi dibuka
   dengan rentetan penekanan tombol ~150–200 ms (keadaan awal ruangan
   diketikkan), lalu sebagian besar durasi berjalan pada satu angka.
   `count_s07` tidak berubah sama sekali selama 373 detik; `count_s09` seluruh
   26 event-nya selesai dalam 20 detik pertama dari 352 detik.

2. **Rentang label melompat: 0, lalu 7–16.** `count_s10` memberi kelas 0, tapi
   tidak ada apa pun di antara 1 dan 6 selain artefak pengetikan. Jadi yang
   tersedia pada dasarnya dua rezim — kosong dan penuh — bukan tangga bertingkat.

3. **Penempatan board per zona belum diketahui** (per 2026-09-14). Analisis
   zona A/B/C/D karena itu DITUNDA; kolom per zona tetap dibawa di tabel label
   supaya tinggal ditempel saat denah tersedia.

4. **`count_s10` direkam ~1 jam setelah sesi lain** (15:19 vs 12:50–14:49).
   Perbedaan apa pun antara kosong dan berpenghuni karena itu tercampur dengan
   hanyutan kanal selama satu jam. Bagian 4b menguji hal ini secara eksplisit,
   bukan mengabaikannya.

### Akibatnya untuk pemodelan

Ukuran sampel efektif **bukan** jumlah jendela (ribuan), melainkan jumlah
*kondisi okupansi yang berbeda* — di seluruh dataset hanya ada belasan. Jendela
yang bersebelahan sangat berkorelasi. Karena itu:

> Akurasi tinggi dari pembagian train/test acak per jendela **tidak berarti
> apa-apa** di sini: model cukup menghafal sesi. Setiap evaluasi harus memakai
> sesi sebagai grup.

Notebook ini karena itu tidak melatih model. Tujuannya menjawab dua pertanyaan:

1. **Apakah CSI membedakan ruangan kosong dari ruangan berpenghuni?** (Bagian 4b
   — baru, dimungkinkan oleh `count_s10`.)
2. **Apakah CSI bereaksi terhadap perpindahan orang di dalam ruangan yang sudah
   penuh?** (Bagian 4 — pertanyaan yang jauh lebih sulit.)

Kedua jawabannya berbeda tajam, dan perbedaan itulah temuan utama notebook ini.
""")

code(r"""
import os, sys, glob, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

# Paket terpasang lewat `pip install -e .` di akar ml_people_count/.
# Fallback ke ../src supaya notebook tetap jalan tanpa instalasi.
sys.path.insert(0, os.path.abspath(os.path.join("..", "src")))
from csi_occupancy import datasets as loader
from csi_occupancy import ZONES

warnings.filterwarnings("ignore", category=RuntimeWarning)
pd.set_option("display.width", 140)
pd.set_option("display.max_columns", 60)

mpl.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 140,
    "axes.grid": True, "grid.alpha": 0.3,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 9,
})

# Gambar ke results/figures/ (di luar folder sumber), bukan ke sebelah notebook.
FIGDIR = os.path.abspath(os.path.join("..", "results", "figures"))
os.makedirs(FIGDIR, exist_ok=True)

SESSIONS = loader.list_sessions()
print("sesi:", SESSIONS)
""")

# ---------------------------------------------------------------- tahap 1
md(r"""
---
## 1. Inventaris dan integritas data

Sebelum menghitung fitur apa pun: apakah file-nya utuh, dan apakah keempat board
benar-benar merekam sepanjang sesi? Cek ini murah dan menyelamatkan analisis
berjam-jam — board yang mati di tengah jalan tidak memunculkan error, hanya
angka yang salah.
""")

code(r"""
rows = []
for s in SESSIONS:
    for f in sorted(glob.glob(os.path.join(loader.DATA_DIR, s, "*.bin"))):
        n = loader.read_node(f)
        span = n["t"].max() - n["t"].min()
        rows.append({
            "session": s, "board": n["tag"], "n_pkt": n["n_pkt"],
            "span_s": round(span, 1),
            "rate_hz": round(n["n_pkt"] / span, 1),
            "n_sub": n["amp"].shape[1],
            "size_mb": round(os.path.getsize(f) / 1e6, 1),
        })
inv = pd.DataFrame(rows)
inv
""")

code(r"""
# Durasi rekaman tiap board relatif terhadap board terpanjang di sesinya.
# Board yang berhenti lebih awal akan terlihat sebagai batang pendek.
inv["span_frac"] = inv.groupby("session")["span_s"].transform(lambda v: v / v.max())

fig, ax = plt.subplots(figsize=(9, 3.4))
boards = sorted(inv["board"].unique())
w = 0.8 / len(boards)
colors = dict(zip(boards, plt.cm.tab10.colors))
for i, b in enumerate(boards):
    sub = inv[inv["board"] == b].set_index("session").reindex(SESSIONS)
    x = np.arange(len(SESSIONS)) + i * w - 0.4 + w / 2
    ax.bar(x, sub["span_frac"].fillna(0), width=w, label=b, color=colors[b])
ax.axhline(1.0, color="k", lw=0.8, ls=":")
ax.set_xticks(range(len(SESSIONS)))
ax.set_xticklabels([s.replace("count_", "") for s in SESSIONS])
ax.set_ylabel("durasi rekam / durasi sesi")
ax.set_title("Cakupan tiap board per sesi (1.0 = merekam penuh)")
ax.legend(title="board", ncol=4, fontsize=8)
plt.tight_layout(); plt.savefig(f"{FIGDIR}/01_board_coverage.png"); plt.show()

print("Board yang tidak merekam penuh:")
print(inv[inv["span_frac"] < 0.95][["session","board","span_s","span_frac"]]
      .to_string(index=False))
print("\nSesi tanpa board lengkap:")
cnt = inv.groupby("session")["board"].count()
print(cnt[cnt < 4].to_string())
""")

md(r"""
**Yang harus terbaca dari grafik di atas.** Dua sesi cacat, dan keduanya cacat
dengan cara yang tidak memunculkan pesan error:

- `count_s01` — board `bf` berhenti setelah ~11 detik dari sesi 293 detik.
  Ukuran file-nya pun kecil (0.5 MB vs ~11 MB), tapi file tetap valid dan
  terbaca. Sesi ini **efektif 3 board**.
- `count_s02` — board `bf` tidak ada sama sekali (hanya 3 file `.bin`).

Runbook counting mensyaratkan keempat board terlihat sebelum sesi dimulai,
justru untuk mencegah ini. Kedua sesi tetap dipakai sebagai sesi 3-board, dan
kolom `n_boards` serta `dropped_boards` dibawa ke seluruh analisis supaya vektor
fitur 3-board dan 4-board tidak pernah tercampur diam-diam.

> **Jebakan yang sempat menjerat notebook ini.** Cara wajar membentuk jendela
> adalah memakai irisan waktu ketika semua board aktif. Di `count_s01` irisan itu
> tinggal 11 detik gara-gara `bf` — 9 jendela dari sesi 293 detik, 97% terbuang
> tanpa satu pun pesan error. Karena itu `window_features()` **membuang** board
> yang cakupannya di bawah 50% board terpanjang, bukan membiarkannya memotong
> rentang sesi. Setelah diperbaiki `count_s01` memberi 291 jendela.

Laju paket ~36–40 Hz di semua board sesuai dengan yang sudah terukur di proyek
ini. Angka "~10 pkt/s" di `RUNBOOK.md` dan komentar firmware keliru; ~40 Hz
adalah normal, bukan bug.
""")

code(r"""
# Jarak antar paket: apakah sampling benar-benar seragam?
n = loader.read_node(glob.glob(os.path.join(loader.DATA_DIR, "count_s07", "node38*.bin"))[0])
dt = np.diff(n["t"]) * 1000

fig, axes = plt.subplots(1, 2, figsize=(10, 3.2))
axes[0].hist(dt[dt < 150], bins=120, color="steelblue")
axes[0].set_xlabel("jarak antar paket (ms)"); axes[0].set_ylabel("jumlah")
axes[0].set_title("Sebaran jarak antar paket (board 38, s07)")
axes[1].hist(dt[dt < 150], bins=120, color="steelblue", cumulative=True,
             density=True, histtype="step", lw=1.5)
axes[1].set_xlabel("jarak antar paket (ms)"); axes[1].set_ylabel("proporsi kumulatif")
axes[1].set_title("CDF")
for q in (0.1, 0.5, 0.9):
    axes[1].axhline(q, color="grey", lw=0.6, ls=":")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/02_interpacket.png"); plt.show()

print("persentil jarak antar paket (ms):",
      {f"p{q}": round(float(np.percentile(dt, q)), 2) for q in (10, 25, 50, 75, 90, 99)})
print(f"paket dengan jarak <5 ms: {(dt < 5).mean():.1%}")
""")

md(r"""
Sampling **tidak seragam**: median ~20 ms tapi ekor bawah jauh lebih rapat —
sebagian besar paket datang berkelompok. Ini konsisten dengan mekanismenya: ping
100 ms hanya *memicu* lalu lintas, dan yang terekam adalah semua frame
`sig_len=114` dari router.

Konsekuensi praktis: statistik per jendela waktu tetap sah, tapi apa pun yang
mengasumsikan laju cuplik konstan (FFT langsung atas paket mentah, filter dengan
frekuensi cutoff tetap) **tidak sah** tanpa resampling dulu. Untuk skripsi:
tulis "~40 paket/detik dengan jarak tidak seragam", jangan "sampling rate 10 Hz".
""")

# ---------------------------------------------------------------- tahap 2
md(r"""
---
## 2. Struktur label okupansi

Label disimpan sebagai **interval**, bukan cuplikan per waktu. Penggabungan ke
CSI harus lewat `host_time` (waktu absolut), bukan `t_rel` — `t_rel` dihitung
sejak pencatat label dijalankan, yang tidak sama dengan saat kolektor mulai.
Menjoin lewat `t_rel` menggeser seluruh label beberapa detik tanpa error apa pun.
""")

code(r"""
occ_all, ev_all = {}, {}
summary = []
for s in SESSIONS:
    occ = loader.load_occupancy(s); ev = loader.load_events(s)
    occ_all[s], ev_all[s] = occ, ev
    dur = occ["t_end"].iloc[-1] - occ["t_start"].iloc[0]
    # "Transisi nyata" = kejadian yang TIDAK termasuk rentetan pembuka.
    #
    # Ambang "10 detik pertama" ternyata terlalu naif: di count_s09 pengetikan
    # keadaan awal berlanjut sampai detik 19.5 (termasuk 5 orang masuk zona B
    # lalu kelimanya keluar lagi), sehingga 17 penekanan tombol terhitung
    # "nyata" padahal semuanya bagian dari penyiapan.
    #
    # Aturan yang dipakai: rentetan pembuka = deretan event di awal yang jarak
    # antar-penekanannya < 3 detik. Begitu ada jeda >= 3 detik, sisanya dianggap
    # perubahan okupansi sungguhan.
    if len(ev):
        gaps = ev["t_rel"].diff().fillna(ev["t_rel"].iloc[0])
        after_burst = np.where(gaps >= 3.0)[0]
        first_real = after_burst[0] if len(after_burst) else len(ev)
        real = ev.iloc[first_real:]
    else:
        real = ev
    # Jumlah transisi saja menipu: di count_s09 ada 17 "transisi" tapi SEMUANYA
    # selesai dalam 20 detik pertama dari 352 detik. Yang menentukan kegunaan
    # sebuah sesi bukan banyaknya event, melainkan SEBERAPA LAMA okupansi
    # benar-benar bervariasi. Kolom `span_real_s` mengukur itu.
    span_real = (real["t_rel"].max() - real["t_rel"].min()) if len(real) else 0.0
    summary.append({
        "session": s, "dur_s": round(dur, 1),
        "n_events": len(ev), "n_burst": len(ev) - len(real),
        "n_real_transitions": len(real),
        "span_real_s": round(span_real, 1),
        "last_event_s": round(ev["t_rel"].max(), 1) if len(ev) else 0.0,
        "total_min": int(occ["total"].min()), "total_max": int(occ["total"].max()),
        "final_total": int(occ["total"].iloc[-1]),
        "hold_frac": round(occ["dur"].max() / dur, 3),
    })
lab_summary = pd.DataFrame(summary)
lab_summary
""")

code(r"""
fig, axes = plt.subplots(4, 2, figsize=(12, 9), sharex=False)
for ax, s in zip(axes.ravel(), SESSIONS):
    occ = occ_all[s]
    t0 = occ["t_start"].iloc[0]
    t = np.repeat((occ["t_start"] - t0).to_numpy(), 2)[1:]
    t = np.append(t, occ["t_end"].iloc[-1] - t0)
    y = np.repeat(occ["total"].to_numpy(), 2)
    ax.plot(t, y, lw=1.4, color="crimson")
    ax.fill_between(t, 0, y, color="crimson", alpha=0.12)
    ax.set_title(f"{s.replace('count_','')}  (maks {int(occ['total'].max())} orang)",
                 fontsize=9)
    ax.set_ylabel("total orang"); ax.set_ylim(0, 17)
    ax.set_xlabel("waktu sejak mulai (s)")
plt.suptitle("Okupansi total sepanjang waktu, per sesi", y=1.005)
plt.tight_layout(); plt.savefig(f"{FIGDIR}/03_occupancy_timeline.png"); plt.show()
""")

md(r"""
**Inilah kendala utama dataset ini, terlihat langsung.** Setiap sesi melonjak
dari 0 ke nilai akhirnya dalam beberapa detik pertama, lalu mendatar. Kolom
`hold_frac` di tabel sebelumnya mengukurnya: proporsi durasi sesi yang dihabiskan
pada satu angka okupansi.

Lonjakan pembuka itu bukan orang berjalan masuk — di `count_s06`, lima orang
"masuk" zona C dalam 0.76 detik dan delapan masuk zona D dalam 1.3 detik. Itu
papan ketik, yaitu keadaan awal ruangan yang diketikkan di awal rekaman (runbook
menyediakan `--initial` persis untuk keperluan ini).

Yang bisa dipakai untuk belajar hanyalah **transisi setelah lonjakan pembuka**.
Jumlahnya di kolom `n_real_transitions`.
""")

code(r"""
fig, ax = plt.subplots(figsize=(9, 3.2))
x = np.arange(len(lab_summary))
ax.bar(x - 0.2, lab_summary["n_burst"], width=0.4,
       label="rentetan pembuka", color="lightgrey", edgecolor="grey")
ax.bar(x + 0.2, lab_summary["n_real_transitions"], width=0.4,
       label="transisi nyata (>10 s)", color="seagreen")
ax.set_xticks(x); ax.set_xticklabels([s.replace("count_","") for s in SESSIONS])
ax.set_ylabel("jumlah event"); ax.legend()
ax.set_title("Event label: pengetikan keadaan awal vs perubahan okupansi nyata")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/04_event_split.png"); plt.show()

usable = lab_summary.sort_values("span_real_s", ascending=False)
print(usable[["session","n_real_transitions","span_real_s","last_event_s",
              "total_min","total_max","hold_frac"]].to_string(index=False))
""")

md(r"""
**Jumlah transisi saja menipu — lihat `span_real_s`.** `count_s09` punya 17
"transisi", angka kedua terbanyak, tapi seluruh 26 event-nya selesai pada detik
19.5 dari sesi 352 detik. Yang menentukan kegunaan sebuah sesi bukan banyaknya
penekanan tombol melainkan berapa lama okupansi benar-benar bervariasi.

Peringkat kegunaan sesi, diurutkan menurut rentang waktu variasi:

- **`count_s03`** — variasi terbentang ~277 detik. Sesi terbaik, dan satu-satunya
  yang punya perubahan okupansi tersebar sepanjang rekaman.
- **`count_s05`** — variasi ~67 detik (t≈79–146 s).
- **`count_s01`, `count_s02`, `count_s04`, `count_s06`** — variasi 9–15 detik,
  semuanya terkumpul di satu titik rekaman.
- **`count_s09`** — 17 event tapi semuanya dalam 20 detik pertama; sisanya 333
  detik konstan di 16 orang. Praktis satu kondisi.
- **`count_s08`** — 2 transisi.
- **`count_s07`** — **nol** transisi.
- **`count_s10`** — **ruangan kosong**, nol event sepanjang 290 detik. Ini bukan
  kelemahan melainkan justru gunanya: acuan untuk Bagian 4b.
""")

code(r"""
# Sebaran waktu per jumlah orang, digabung seluruh sesi.
tot_time = {}
for s in SESSIONS:
    for _, r in occ_all[s].iterrows():
        tot_time[int(r["total"])] = tot_time.get(int(r["total"]), 0) + r["dur"]
ser = pd.Series(tot_time).sort_index()

fig, ax = plt.subplots(figsize=(9, 3))
ax.bar(ser.index, ser.values, color="steelblue")
ax.set_xlabel("jumlah orang (total)"); ax.set_ylabel("total detik")
ax.set_title("Berapa lama dataset menghabiskan waktu di tiap jumlah orang")
ax.set_xticks(range(0, 18))
plt.tight_layout(); plt.savefig(f"{FIGDIR}/05_class_balance.png"); plt.show()

print(ser.round(1).to_string())
print(f"\nkelas dengan >30 s data: {sorted(ser[ser > 30].index.tolist())}")
""")

md(r"""
Sebarannya **bimodal, bukan bertingkat**. Kelas 0 sekarang punya ~290 detik data
sungguhan berkat `count_s10`. Kelas tinggi (≈8–16) punya banyak data. Tapi di
antaranya — 1 sampai 7 orang — hampir seluruhnya hanya muncul selama **pecahan
detik** saat rentetan pembuka berlangsung; itu artefak pengetikan, bukan
pengamatan ruangan berisi 3 orang.

Artinya: dataset ini mendukung pertanyaan **"kosong atau berpenghuni?"** (dua
rezim, keduanya punya data berlimpah), tapi tidak mendukung **"berapa orang?"**
sebagai regresi atau klasifikasi bertingkat, karena separuh rentangnya kosong.
""")

# ---------------------------------------------------------------- tahap 3
md(r"""
---
## 3. Karakter sinyal CSI

Sekarang sinyalnya sendiri. Tiap paket berisi 256 subcarrier (512 int16
berpasangan I/Q); amplitudo = sqrt(I²+Q²).
""")

code(r"""
sess_demo = "count_s03"
nodes = loader.load_session(sess_demo)
print(f"{sess_demo}: board {sorted(nodes)}")
for tag, n in sorted(nodes.items()):
    print(f"  {tag}: {n['n_pkt']:6d} paket, amp shape {n['amp'].shape}, "
          f"rssi {n['rssi'].mean():.1f} dBm")

amp0 = next(iter(nodes.values()))["amp"]
active = np.where((amp0 > 0).mean(axis=0) > 0.5)[0]
print(f"\nsubcarrier aktif: {len(active)} dari {amp0.shape[1]} "
      f"(indeks {active.min()}..{active.max()})")
""")

code(r"""
fig, axes = plt.subplots(1, 2, figsize=(12, 3.6))
for tag, n in sorted(nodes.items()):
    prof = n["amp"].mean(axis=0)
    axes[0].plot(prof, lw=1, label=tag)
    axes[1].plot(n["amp"].std(axis=0), lw=1, label=tag)
axes[0].set_title("Amplitudo rata-rata per subcarrier")
axes[0].set_xlabel("indeks subcarrier"); axes[0].set_ylabel("amplitudo")
axes[1].set_title("Simpangan baku per subcarrier")
axes[1].set_xlabel("indeks subcarrier"); axes[1].set_ylabel("std")
for a in axes: a.legend(title="board", fontsize=8)
plt.suptitle(f"Profil subcarrier — {sess_demo}", y=1.02)
plt.tight_layout(); plt.savefig(f"{FIGDIR}/06_subcarrier_profile.png"); plt.show()
""")

md(r"""
Dua hal penting terlihat:

1. **Ada subcarrier mati** (amplitudo nol) di tepi dan di tengah — guard band dan
   DC. Fitur apa pun harus dihitung hanya atas subcarrier aktif; memasukkan yang
   nol menambah dimensi tanpa informasi dan merusak normalisasi.

2. **Level antar board berbeda jauh**, dan bedanya bersifat tetap (jarak ke
   router, orientasi antena). Inilah yang seharusnya dihapus oleh normalisasi
   terhadap ruangan kosong. Tanpa baseline itu, model yang membandingkan board
   satu dengan lainnya akan mempelajari geometri pemasangan, bukan okupansi.
""")

code(r"""
fig, axes = plt.subplots(2, 4, figsize=(13, 5.5))
for j, (tag, n) in enumerate(sorted(nodes.items())):
    per_pkt = n["amp"][:, active].mean(axis=1)
    axes[0, j].hist(per_pkt, bins=80, color="steelblue")
    axes[0, j].set_title(f"board {tag} — amplitudo", fontsize=9)
    axes[0, j].set_xlabel("amplitudo rata-rata paket")
    axes[1, j].hist(n["rssi"], bins=np.arange(n["rssi"].min()-0.5,
                                              n["rssi"].max()+1.5), color="indianred")
    axes[1, j].set_title(f"board {tag} — RSSI", fontsize=9)
    axes[1, j].set_xlabel("RSSI (dBm)")
plt.suptitle(f"Sebaran amplitudo dan RSSI per board — {sess_demo}", y=1.01)
plt.tight_layout(); plt.savefig(f"{FIGDIR}/07_distributions.png"); plt.show()

print(pd.DataFrame({
    tag: {"amp_mean": n["amp"][:, active].mean(),
          "amp_std": n["amp"][:, active].mean(axis=1).std(),
          "rssi_mean": n["rssi"].mean(), "rssi_std": n["rssi"].std()}
    for tag, n in sorted(nodes.items())}).T.round(2).to_string())
""")

md(r"""
RSSI terkuantisasi kasar (bilangan bulat dBm, rentang sempit), jadi sebagai fitur
tunggal ia lemah. Tetap dibawa karena catatan riset sebelumnya di proyek ini
menemukan **std RSSI** kira-kira menggandakan diri saat ada orang — yang berguna
sebarannya, bukan nilainya.
""")

# ---------------------------------------------------------------- tahap 4
md(r"""
---
## 4. Apakah CSI bereaksi terhadap perubahan okupansi?

Ini pertanyaan inti notebook. Karena okupansi hampir konstan, ujinya bukan
"korelasi antara fitur dan jumlah orang" melainkan lebih spesifik:
**pada detik-detik ketika label berubah, apakah sinyalnya ikut berubah?**

Sesi `count_s03` dipakai karena transisinya paling banyak dan tersebar.
""")

code(r"""
WIN_S, HOP_S = 2.0, 1.0

# Catatan penting soal board yang mati di tengah sesi:
# jendela hanya dibentuk di rentang waktu yang dicakup SEMUA board yang dipakai.
# Kalau board bf di count_s01 (mati setelah 11 s dari 293 s) ikut dipakai, irisan
# itu menyusut jadi 11 detik -- 9 jendela saja, 97% sesi hilang tanpa error.
# Karena itu window_features() membuang board yang cakupannya < 50% board
# terpanjang, dan mencatatnya di kolom `dropped_boards`.
feat = {}
for s in SESSIONS:
    feat[s] = loader.window_features(s, win_s=WIN_S, hop_s=HOP_S)
    drop = feat[s]["dropped_boards"].iloc[0]
    print(f"{s}: {len(feat[s])} jendela, "
          f"{feat[s]['total'].notna().sum()} berlabel, "
          f"{feat[s]['n_boards'].iloc[0]} board"
          + (f"  [board dibuang: {drop}]" if drop else ""))
F = pd.concat(feat.values(), ignore_index=True)
print("\ngabungan:", F.shape)
""")

code(r"""
def plot_session(s, stat="sub_var", ax=None):
    d = feat[s].dropna(subset=["total"])
    t0 = d["t_mid"].iloc[0]
    tags = [c.split("_")[0] for c in d.columns if c.endswith("_" + stat)]
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 3))
    for tag in sorted(tags):
        v = d[f"{tag}_{stat}"].to_numpy(dtype=float)
        v = (v - np.nanmedian(v)) / (np.nanstd(v) + 1e-9)   # z agar sebanding
        ax.plot(d["t_mid"] - t0, v, lw=0.9, alpha=0.85, label=tag)
    ax.set_ylabel(f"{stat} (z per board)")
    ax2 = ax.twinx()
    ax2.plot(d["t_mid"] - t0, d["total"], color="k", lw=2.0, ls="--",
             label="total orang")
    ax2.set_ylabel("total orang"); ax2.grid(False)
    ev = ev_all[s]; ev = ev[ev["t_rel"] > 10]
    for _, e in ev.iterrows():
        ax.axvline(e["host_time"] - t0, color="crimson", lw=0.7, alpha=0.5)
    ax.set_title(f"{s.replace('count_','')} — {stat} per board vs okupansi "
                 f"(garis merah = transisi label)", fontsize=9)
    ax.set_xlabel("waktu (s)")
    ax.legend(fontsize=7, ncol=4, loc="upper left")
    return ax

fig, axes = plt.subplots(2, 1, figsize=(11, 6.5))
plot_session("count_s03", "sub_var", axes[0])
plot_session("count_s03", "amp_mean", axes[1])
plt.tight_layout(); plt.savefig(f"{FIGDIR}/08_s03_timeseries.png"); plt.show()
""")

md(r"""
Garis merah menandai transisi label. Kalau CSI membawa informasi okupansi,
seharusnya terlihat perubahan tingkat (level shift) di sekitar garis-garis itu.
Sel berikutnya mengukurnya, bukan menilainya dengan mata.
""")

code(r"""
def transition_response(s, stat="sub_var", pad_s=8.0):
    # Bandingkan statistik fitur sebelum vs sesudah tiap transisi label.
    # Pembanding sengaja LOKAL (pad_s detik di kedua sisi), bukan rata-rata
    # sesi: kanal menghanyut perlahan sepanjang rekaman, jadi perbandingan
    # global akan mencampur hanyutan itu dengan efek okupansi.
    d = feat[s].dropna(subset=["total"]).reset_index(drop=True)
    ev = ev_all[s]; ev = ev[ev["t_rel"] > 10]
    tags = sorted({c.split("_")[0] for c in d.columns if c.endswith("_" + stat)})
    out = []
    for _, e in ev.iterrows():
        tc = e["host_time"]
        pre = d[(d["t_mid"] >= tc - pad_s) & (d["t_mid"] < tc)]
        post = d[(d["t_mid"] > tc) & (d["t_mid"] <= tc + pad_s)]
        if len(pre) < 3 or len(post) < 3:
            continue
        rec = {"session": s, "t_rel": round(e["t_rel"], 1),
               "zone": e["zone"], "action": e["action"]}
        for tag in tags:
            a = pre[f"{tag}_{stat}"].to_numpy(dtype=float)
            b = post[f"{tag}_{stat}"].to_numpy(dtype=float)
            pooled = np.sqrt((a.var() + b.var()) / 2) + 1e-9
            rec[tag] = (b.mean() - a.mean()) / pooled      # Cohen's d
        out.append(rec)
    return pd.DataFrame(out)

resp = pd.concat([transition_response(s) for s in SESSIONS], ignore_index=True)
resp = resp.dropna(axis=1, how="all")
print(f"{len(resp)} transisi punya jendela cukup di kedua sisi\n")
board_cols = [c for c in resp.columns if c in ("38","4b","bf","d0")]
print("|Cohen's d| per transisi, ringkasan seluruh board:")
alld = resp[board_cols].to_numpy(dtype=float).ravel()
alld = alld[~np.isnan(alld)]
print(pd.Series(np.abs(alld)).describe().round(2).to_string())
print(f"\nproporsi |d| > 0.8 (efek besar): {(np.abs(alld) > 0.8).mean():.1%}")
print(f"proporsi |d| > 0.5 (efek sedang): {(np.abs(alld) > 0.5).mean():.1%}")
resp.round(2)
""")

code(r"""
# Pembanding: apakah |d| di transisi nyata berbeda dari |d| di waktu ACAK
# ketika tidak ada yang berubah? Tanpa pembanding ini, |d| besar tidak berarti
# apa-apa -- kanal WiFi memang bergerak sendiri.
rng = np.random.default_rng(0)

def null_response(s, stat="sub_var", pad_s=8.0, n_draw=40):
    d = feat[s].dropna(subset=["total"]).reset_index(drop=True)
    ev = ev_all[s]; ev = ev[ev["t_rel"] > 10]
    bad = ev["host_time"].to_numpy()
    tags = sorted({c.split("_")[0] for c in d.columns if c.endswith("_" + stat)})
    lo, hi = d["t_mid"].min() + pad_s, d["t_mid"].max() - pad_s
    if hi <= lo: return []
    vals = []
    for _ in range(n_draw):
        tc = rng.uniform(lo, hi)
        if len(bad) and np.min(np.abs(bad - tc)) < 2 * pad_s:
            continue                      # jangan ambil dekat transisi nyata
        pre = d[(d["t_mid"] >= tc - pad_s) & (d["t_mid"] < tc)]
        post = d[(d["t_mid"] > tc) & (d["t_mid"] <= tc + pad_s)]
        if len(pre) < 3 or len(post) < 3: continue
        for tag in tags:
            a = pre[f"{tag}_{stat}"].to_numpy(dtype=float)
            b = post[f"{tag}_{stat}"].to_numpy(dtype=float)
            pooled = np.sqrt((a.var() + b.var()) / 2) + 1e-9
            vals.append(abs((b.mean() - a.mean()) / pooled))
    return vals

null = np.array([v for s in SESSIONS for v in null_response(s)])
real = np.abs(alld)

fig, ax = plt.subplots(figsize=(8, 3.2))
bins = np.linspace(0, 4, 45)
ax.hist(null, bins=bins, alpha=0.6, density=True, label=f"waktu acak (n={len(null)})",
        color="grey")
ax.hist(real, bins=bins, alpha=0.6, density=True, label=f"transisi label (n={len(real)})",
        color="seagreen")
ax.set_xlabel("|Cohen's d| sebelum vs sesudah"); ax.set_ylabel("densitas")
ax.set_title("Respons di transisi label vs di waktu acak")
ax.legend()
plt.tight_layout(); plt.savefig(f"{FIGDIR}/09_transition_vs_null.png"); plt.show()

from scipy import stats
u, p = stats.mannwhitneyu(real, null, alternative="greater")
print(f"median |d| transisi : {np.median(real):.2f}")
print(f"median |d| acak     : {np.median(null):.2f}")
print(f"Mann-Whitney U satu-sisi: p = {p:.3g}")
print("\nArti p: peluang melihat perbedaan sebesar ini kalau transisi label")
print("sebenarnya tidak istimewa dibanding waktu sembarang.")
""")

md(r"""
**Hasilnya: kedua histogram bertumpuk.** Pada `sub_var` dengan jendela 8 detik,
median |d| di transisi label justru sedikit LEBIH RENDAH daripada di waktu acak
(0.58 vs 0.74; p = 0.48). Dengan kata lain, perubahan sinyal di saat orang
berpindah zona tidak lebih besar daripada gejolak kanal di waktu sembarang.

Satu uji dengan satu pilihan parameter bukan bukti, apalagi untuk hasil negatif.
Sel berikut menyapu enam statistik × tiga lebar jendela sebelum menyimpulkan.
""")

code(r"""
# Sapuan: apakah kesimpulan berubah kalau statistik atau lebar jendela diganti?
# Hasil negatif wajib diuji begini -- kalau tidak, yang dilaporkan cuma satu
# pilihan parameter yang kebetulan.
BOARD_SET = ("38", "4b", "bf", "d0")

def real_d(s, stat, pad):
    r = transition_response(s, stat, pad)
    cols = [c for c in r.columns if c in BOARD_SET]
    if not cols:
        return np.array([])
    return np.abs(r[cols].to_numpy(dtype=float).ravel())

rows = []
for stat in ["sub_var", "amp_mean", "amp_std", "sub_std_spatial",
             "rssi_std", "rssi_mean"]:
    for pad in (4.0, 8.0, 15.0):
        R = np.concatenate([real_d(s, stat, pad) for s in SESSIONS])
        N = np.concatenate([null_response(s, stat, pad, n_draw=60) or [np.nan]
                            for s in SESSIONS])
        R = R[np.isfinite(R)]; N = N[np.isfinite(N)]
        u, p = stats.mannwhitneyu(R, N, alternative="greater")
        rows.append({"stat": stat, "pad_s": pad, "n": len(R),
                     "med_transisi": round(float(np.median(R)), 2),
                     "med_acak": round(float(np.median(N)), 2),
                     "p": round(float(p), 4)})
sweep = pd.DataFrame(rows)
sweep["signifikan"] = np.where(sweep["p"] < 0.05, "ya", "")
sweep
""")

code(r"""
fig, ax = plt.subplots(figsize=(9, 3.6))
piv = sweep.pivot(index="stat", columns="pad_s", values="p")
im = ax.imshow(piv.to_numpy(), cmap="RdYlGn_r", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(piv.columns)))
ax.set_xticklabels([f"{c:.0f} s" for c in piv.columns])
ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index)
for i in range(piv.shape[0]):
    for j in range(piv.shape[1]):
        v = piv.iloc[i, j]
        ax.text(j, i, f"{v:.3f}", ha="center", va="center", fontsize=8,
                color="white" if v > 0.6 else "black")
ax.set_xlabel("lebar jendela pembanding"); ax.set_ylabel("")
ax.set_title("p-value: respons di transisi label > respons di waktu acak?\n"
             "(hijau = signifikan, merah = tidak)")
ax.grid(False)
plt.colorbar(im, ax=ax, label="p")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/09b_sweep.png"); plt.show()

print(f"kombinasi signifikan (p<0.05): {(sweep['p'] < 0.05).sum()} dari {len(sweep)}")
""")

md(r"""
**Bacaan yang jujur atas sapuan ini.** Hasilnya tidak seragam, dan
ketidakseragaman itu sendiri informatif:

- **`rssi_std` pada jendela 8 dan 15 detik** memberi p < 0.0001, dengan median
  |d| jelas lebih tinggi di transisi (0.97 vs 0.67 dan 0.73 vs 0.45). Ini hasil
  terkuat dan satu-satunya yang bertahan di lebih dari satu skala waktu. Sejalan
  dengan catatan riset sebelumnya di proyek ini bahwa std RSSI kira-kira
  menggandakan diri saat ada orang.
- **`amp_std` pada jendela 4 detik** signifikan (p = 0.0001) tapi hilang begitu
  jendela diperlebar.
- **`sub_var` dan `sub_std_spatial`** hanya mendekati ambang (p ≈ 0.07–0.08) dan
  tidak pernah melewatinya.
- **`amp_mean` dan `rssi_mean` tidak pernah signifikan** pada lebar mana pun.
  Level rata-rata memang tumpul — sama seperti temuan di kerja lokalisasi, di
  mana amplitudo rata-rata hampir buta (36%) sementara variance jauh lebih baik.

Jadi ada sinyal, tapi **lemah dan bergantung pada pilihan statistik dan skala
waktu**: hanya 3 dari 18 kombinasi yang signifikan, dan semuanya ukuran
*sebaran* (std), tidak pernah ukuran *level*. Untuk transisi yang hanya
memindahkan 1 dari 16 orang (~6%), efek selemah itu memang masuk akal — tapi ia
belum cukup kuat untuk dijadikan dasar penghitung orang.

> Jangan laporkan ini sebagai "CSI tidak bereaksi". Laporkan sebagai: pada
> dataset ini, respons terhadap perpindahan satu orang hanya terdeteksi lewat
> fitur berbasis sebaran, dan tidak konsisten lintas skala waktu.
""")

# --------------------------------------------------------------- tahap 4b
md(r"""
---
## 4b. Kosong lawan berpenghuni — analisis yang dibuka oleh `count_s10`

Bagian ini **tidak ada di versi pertama notebook** karena belum ada capture
ruangan kosong. `count_s10` (290 detik, 4 board, nol event) mengubahnya.

Pertanyaannya sederhana tapi mendasar: **apakah CSI bisa membedakan ruangan
kosong dari ruangan berisi 16 orang?** Kalau tidak bisa, seluruh gagasan
menghitung orang dari CSI di setup ini gugur. Kalau bisa, barulah pertanyaan
yang lebih halus (berapa banyak orang) layak ditanyakan.
""")

code(r"""
EMPTY = "count_s10"
D_all = F.dropna(subset=["total"]).copy()
emp = D_all[D_all["session"] == EMPTY]
full = D_all[(D_all["session"] != EMPTY) & (D_all["total"] >= 13)]
print(f"jendela kosong  : {len(emp)}  (label total = "
      f"{sorted(emp['total'].unique())})")
print(f"jendela penuh   : {len(full)} (total >= 13 orang)")

rows = []
for tag in ["38", "4b", "bf", "d0"]:
    for st in loader.STATS:
        c = f"{tag}_{st}"
        if c not in D_all.columns:
            continue
        a = emp[c].dropna().to_numpy(dtype=float)
        b = full[c].dropna().to_numpy(dtype=float)
        if len(a) < 5 or len(b) < 5:
            continue
        pooled = np.sqrt((a.var() + b.var()) / 2) + 1e-12
        u, p = stats.mannwhitneyu(b, a, alternative="two-sided")
        rows.append({"board": tag, "stat": st,
                     "kosong": round(a.mean(), 3), "penuh": round(b.mean(), 3),
                     "rasio": round(b.mean() / a.mean(), 3),
                     "cohen_d": round((b.mean() - a.mean()) / pooled, 2),
                     "p": p})
ef = pd.DataFrame(rows).sort_values("cohen_d", key=np.abs, ascending=False)
ef.head(12)
""")

code(r"""
fig, ax = plt.subplots(figsize=(9, 4.6))
top = ef.head(14).iloc[::-1]
lbl = top["board"] + "_" + top["stat"]
cols = ["seagreen" if d > 0 else "indianred" for d in top["cohen_d"]]
ax.barh(range(len(top)), top["cohen_d"], color=cols)
ax.set_yticks(range(len(top))); ax.set_yticklabels(lbl, fontsize=8)
ax.axvline(0, color="k", lw=0.8)
for x, ls in ((0.8, ":"), (-0.8, ":")):
    ax.axvline(x, color="grey", lw=0.7, ls=ls)
ax.set_xlabel("Cohen's d  (penuh − kosong)")
ax.set_title("Efek okupansi: ruangan penuh vs ruangan kosong\n"
             "(garis putus = ambang efek besar |d|=0.8)")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/14_empty_vs_full.png"); plt.show()

print(f"fitur dengan |d| > 0.8 : {(ef['cohen_d'].abs() > 0.8).sum()} dari {len(ef)}")
print(f"fitur dengan |d| > 1.5 : {(ef['cohen_d'].abs() > 1.5).sum()}")
""")

md(r"""
Efeknya **besar** — jauh lebih besar daripada apa pun di Bagian 4. Tapi ada satu
kemungkinan lain yang harus disingkirkan sebelum ini boleh disebut efek okupansi.

`count_s10` direkam pukul 15:19, sedangkan sesi berpenghuni pukul 12:50–14:49.
Perbedaan yang terlihat bisa saja **hanyutan kanal selama satu jam**, bukan
akibat orangnya. Ujinya: bandingkan jarak "kosong vs berpenghuni" terhadap
sebaran antar sesi berpenghuni itu sendiri. Kalau ruangan kosong hanya sejauh
satu sesi berpenghuni dari sesi berpenghuni lain, tidak ada yang terbukti.
""")

code(r"""
# Apakah ruangan kosong benar-benar DI LUAR sebaran sesi berpenghuni?
rows = []
occ_sessions = [s for s in SESSIONS if s != EMPTY]
for tag in ["38", "4b", "bf", "d0"]:
    for st in loader.STATS:
        c = f"{tag}_{st}"
        if c not in D_all.columns:
            continue
        per = D_all[D_all["session"] != EMPTY].groupby("session")[c].mean().dropna()
        e = emp[c].mean()
        if len(per) < 4 or not np.isfinite(e) or per.std() == 0:
            continue
        rows.append({
            "fitur": c,
            "kosong": round(e, 3),
            "berpenghuni_mean": round(per.mean(), 3),
            "berpenghuni_sd": round(per.std(), 3),
            "z_kosong": round((e - per.mean()) / per.std(), 2),
            "di_luar_rentang": bool(e < per.min() or e > per.max()),
        })
drift = pd.DataFrame(rows).sort_values("z_kosong", key=np.abs, ascending=False)
print(f"fitur yang nilai kosongnya DI LUAR rentang semua sesi berpenghuni: "
      f"{drift['di_luar_rentang'].sum()} dari {len(drift)}")
drift.head(12)
""")

code(r"""
best = drift.iloc[0]["fitur"]
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

# kiri: rata-rata per sesi, kosong ditandai
per = D_all[D_all["session"] != EMPTY].groupby("session")[best].mean().dropna()
axes[0].scatter(range(len(per)), per.values, s=45, color="steelblue",
                label="sesi berpenghuni", zorder=3)
axes[0].axhline(emp[best].mean(), color="crimson", lw=1.8, ls="--",
                label="ruangan KOSONG (s10)")
axes[0].axhspan(per.mean() - per.std(), per.mean() + per.std(),
                color="steelblue", alpha=0.15, label="±1 SD berpenghuni")
axes[0].set_xticks(range(len(per)))
axes[0].set_xticklabels([s.replace("count_", "") for s in per.index],
                        rotation=45, fontsize=8)
axes[0].set_ylabel(best); axes[0].legend(fontsize=8)
axes[0].set_title(f"{best}: kosong vs tiap sesi berpenghuni")

# kanan: sebaran jendela
axes[1].hist(full[best].dropna(), bins=45, alpha=0.65, density=True,
             color="steelblue", label="penuh (>=13 orang)")
axes[1].hist(emp[best].dropna(), bins=45, alpha=0.65, density=True,
             color="crimson", label="kosong")
axes[1].set_xlabel(best); axes[1].set_ylabel("densitas")
axes[1].legend(fontsize=8); axes[1].set_title("Sebaran per jendela")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/15_empty_vs_drift.png"); plt.show()
""")

code(r"""
# Uji paling tegas: bisakah model membedakan kosong vs berpenghuni kalau
# diuji pada SESI yang belum pernah dilihat? Leave-one-session-out, sehingga
# model tidak bisa menang dengan menghafal sidik jari sesi.
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

# Hanya fitur yang ada di SEMUA sesi. Board bf gugur seluruhnya karena hilang
# di s01/s02 -- dipakai juga nanti di Bagian 6, jadi didefinisikan sekali di sini.
feat_cols = [c for c in F.columns
             if any(c.endswith("_" + s) for s in loader.STATS)]
common = [c for c in feat_cols if F[c].notna().all()]
print(f"fitur dipakai: {len(common)} dari {len(feat_cols)} "
      f"(hanya yang lengkap di semua sesi)")

Db = D_all.dropna(subset=common).copy()
Db["is_empty"] = (Db["session"] == EMPTY).astype(int)
Xb = Db[common].to_numpy(dtype=float)
yb = Db["is_empty"].to_numpy()
gb = Db["session"].to_numpy()

pipe = make_pipeline(StandardScaler(),
                     RandomForestClassifier(n_estimators=300, random_state=0,
                                            n_jobs=-1, class_weight="balanced"))
pred = cross_val_predict(pipe, Xb, yb, groups=gb, cv=LeaveOneGroupOut())

from sklearn.metrics import balanced_accuracy_score, confusion_matrix
print("Leave-one-session-out, kelas: 0 = berpenghuni, 1 = kosong")
print(f"balanced accuracy : {balanced_accuracy_score(yb, pred):.3f}")
print(f"jendela kosong terdeteksi benar : "
      f"{(pred[yb == 1] == 1).sum()} / {(yb == 1).sum()}")
print(f"jendela berpenghuni salah disebut kosong: "
      f"{(pred[yb == 0] == 1).sum()} / {(yb == 0).sum()}")
print("\nmatriks konfusi (baris = sebenarnya, kolom = prediksi):")
print(pd.DataFrame(confusion_matrix(yb, pred),
                   index=["berpenghuni", "kosong"],
                   columns=["berpenghuni", "kosong"]).to_string())
""")

md(r"""
**Perhatikan apa yang diuji di sel terakhir dan apa yang tidak.** Karena hanya
ada SATU sesi kosong, leave-one-session-out berarti: saat giliran `count_s10`
menjadi data uji, model dilatih **tanpa satu pun contoh ruangan kosong**. Model
praktis dipaksa menebak "kosong" untuk sesuatu yang belum pernah dilihatnya.

Jadi angka yang keluar di bawah 1.0 **bukan** bukti bahwa kosong dan berpenghuni
tidak terbedakan — itu konsekuensi tak terhindarkan dari punya satu sesi kosong.
Yang sungguh-sungguh informatif adalah dua hasil sebelumnya:

- Ukuran efek `|d|` antara kosong dan penuh, yang jauh melampaui apa pun di
  Bagian 4.
- Berapa banyak fitur yang nilai kosongnya jatuh **di luar rentang seluruh
  sembilan sesi berpenghuni** — itu tidak bisa dijelaskan oleh hanyutan kanal
  biasa, karena kesembilan sesi itu sendiri terbentang sepanjang dua jam.

> Untuk membuat klaim "kosong vs berpenghuni" benar-benar kokoh, yang dibutuhkan
> adalah **beberapa sesi kosong pada waktu berbeda**, bukan satu.
""")

# ---------------------------------------------------------------- tahap 5
md(r"""
---
## 5. Hubungan fitur dengan jumlah orang

Bagian ini sengaja dipasangkan dengan pemeriksaan pembanding. Korelasi antara
fitur dan `total` di data ini **mudah sekali menyesatkan**: karena tiap sesi
praktis satu angka okupansi, korelasi apa pun antar-sesi sebetulnya mengukur
"beda sesi", bukan "beda jumlah orang".
""")

code(r"""
# feat_cols / common sudah didefinisikan di Bagian 4b.
D = F.dropna(subset=["total"]).copy()

# Korelasi NAIF: semua sesi dicampur. Inilah angka yang tampak bagus tapi salah.
naive = (D[feat_cols + ["total"]].corr(method="spearman")["total"]
         .drop("total").dropna().sort_values(key=np.abs, ascending=False))

# Korelasi DALAM sesi: fitur dan label sama-sama dipusatkan per sesi dulu,
# sehingga perbedaan antar sesi dibuang dan yang tersisa hanya variasi internal.
W = D.copy()
for c in feat_cols + ["total"]:
    W[c] = W[c] - W.groupby("session")[c].transform("mean")
within = (W[feat_cols + ["total"]].corr(method="spearman")["total"]
          .drop("total").dropna().sort_values(key=np.abs, ascending=False))

cmp = pd.DataFrame({"naif_antar_sesi": naive, "dalam_sesi": within}).dropna()
print("10 fitur dengan |korelasi naif| tertinggi:\n")
print(cmp.reindex(naive.index[:10]).round(3).to_string())
""")

code(r"""
fig, ax = plt.subplots(figsize=(6.2, 5.2))
ax.scatter(cmp["naif_antar_sesi"], cmp["dalam_sesi"], s=22, alpha=0.75,
           color="steelblue")
lim = 1.02
ax.plot([-lim, lim], [-lim, lim], color="grey", lw=0.8, ls=":")
ax.axhline(0, color="k", lw=0.7); ax.axvline(0, color="k", lw=0.7)
ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
ax.set_xlabel("korelasi naif (semua sesi dicampur)")
ax.set_ylabel("korelasi dalam sesi (efek sesi dibuang)")
ax.set_title("Korelasi fitur terhadap jumlah orang")
for name in naive.index[:6]:
    if name in cmp.index:
        ax.annotate(name, (cmp.loc[name, "naif_antar_sesi"],
                           cmp.loc[name, "dalam_sesi"]),
                    fontsize=7, alpha=0.8,
                    xytext=(3, 3), textcoords="offset points")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/10_corr_naive_vs_within.png"); plt.show()

print(f"median |korelasi| naif      : {cmp['naif_antar_sesi'].abs().median():.3f}")
print(f"median |korelasi| dalam sesi: {cmp['dalam_sesi'].abs().median():.3f}")
print(f"\nfitur yang korelasinya menyusut >50% setelah efek sesi dibuang: "
      f"{(cmp['dalam_sesi'].abs() < 0.5 * cmp['naif_antar_sesi'].abs()).sum()} "
      f"dari {len(cmp)}")
""")

md(r"""
**Jarak titik-titik dari garis diagonal adalah ukuran seberapa besar korelasi
naif itu palsu.** Titik yang jauh di kanan (korelasi naif tinggi) tapi dekat nol
secara vertikal berarti: fitur itu membedakan sesi, bukan membedakan jumlah
orang. Di data ini sebagian besar fitur berperilaku begitu, dan itu memang yang
diharapkan — dengan okupansi hampir konstan per sesi, "sesi" dan "jumlah orang"
nyaris merupakan variabel yang sama.

Inilah alasan konkret kenapa evaluasi model **harus** memakai sesi sebagai grup.
""")

# ---------------------------------------------------------------- tahap 6
md(r"""
---
## 6. Struktur berdimensi tinggi

PCA dan korelasi antar-subcarrier: berapa banyak dimensi yang sebetulnya
bergerak, dan apakah board-board saling mengonfirmasi.
""")

code(r"""
from sklearn.decomposition import PCA

tag_demo = sorted(nodes)[0]
A = nodes[tag_demo]["amp"][:, active]
corr = np.corrcoef(A.T)

fig, axes = plt.subplots(1, 2, figsize=(11, 4))
im = axes[0].imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
axes[0].set_title(f"Korelasi antar subcarrier (board {tag_demo})")
axes[0].set_xlabel("subcarrier aktif"); axes[0].set_ylabel("subcarrier aktif")
plt.colorbar(im, ax=axes[0], fraction=0.046)

p = PCA(n_components=min(30, A.shape[1])).fit(StandardScaler().fit_transform(A))
axes[1].plot(np.arange(1, len(p.explained_variance_ratio_) + 1),
             np.cumsum(p.explained_variance_ratio_), marker="o", ms=3)
axes[1].axhline(0.9, color="crimson", lw=0.8, ls=":")
axes[1].set_xlabel("jumlah komponen"); axes[1].set_ylabel("ragam kumulatif")
axes[1].set_title("PCA atas subcarrier")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/11_pca_subcarrier.png"); plt.show()

k90 = int(np.searchsorted(np.cumsum(p.explained_variance_ratio_), 0.9) + 1)
print(f"komponen untuk 90% ragam: {k90} (dari {A.shape[1]} subcarrier aktif)")
print(f"korelasi rata-rata antar subcarrier: {corr[np.triu_indices_from(corr,1)].mean():.3f}")
""")

md(r"""
Hasilnya: **10 komponen sudah menjelaskan 90% ragam** dari 244 subcarrier aktif.
Menariknya korelasi rata-rata antar subcarrier justru rendah (~0.08) — jadi
redundansinya bukan karena semua subcarrier bergerak bersama, melainkan karena
ragam terkonsentrasi di sedikit arah saja; sisanya sebagian besar derau per
subcarrier yang tidak berkorelasi.

Konsekuensinya sama: 244 subcarrier **bukan** 244 informasi bebas. Memakai
semuanya mentah-mentah sebagai fitur memberi dimensi jauh melebihi jumlah
kondisi okupansi yang tersedia. Reduksi dimensi di sini keharusan, bukan pilihan.
""")

code(r"""
# PCA atas fitur per-jendela, diwarnai per sesi lalu per jumlah orang.
Dp = F.dropna(subset=["total"]).dropna(subset=common)
X = StandardScaler().fit_transform(Dp[common].to_numpy(dtype=float))
pc = PCA(n_components=2).fit_transform(X)

fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
for s in SESSIONS:
    m = (Dp["session"] == s).to_numpy()
    if m.sum():
        axes[0].scatter(pc[m, 0], pc[m, 1], s=8, alpha=0.6,
                        label=s.replace("count_", ""))
axes[0].legend(fontsize=7, ncol=2); axes[0].set_title("PCA jendela — warna = SESI")
axes[0].set_xlabel("PC1"); axes[0].set_ylabel("PC2")

sc = axes[1].scatter(pc[:, 0], pc[:, 1], c=Dp["total"], s=8, alpha=0.7,
                     cmap="viridis")
plt.colorbar(sc, ax=axes[1], label="total orang")
axes[1].set_title("PCA jendela — warna = JUMLAH ORANG")
axes[1].set_xlabel("PC1"); axes[1].set_ylabel("PC2")
plt.tight_layout(); plt.savefig(f"{FIGDIR}/12_pca_windows.png"); plt.show()

print(f"fitur dipakai: {len(common)} (hanya yang ada di semua sesi, "
      f"jadi board bf tidak masuk karena hilang di s01/s02)")
""")

md(r"""
**Perbandingan dua panel ini adalah temuan terpenting notebook.** Kalau gugusan
di panel kiri (warna = sesi) terpisah rapi sementara panel kanan (warna = jumlah
orang) tampak bergradasi mengikuti gugus yang sama, maka yang dipisahkan PCA
adalah **sesi**, bukan **orang** — dan karena tiap sesi punya okupansi
sendiri-sendiri, keduanya memang tak terpisahkan di data ini.

Perhatikan juga: hanya fitur yang ada di semua sesi yang dipakai, sehingga board
`bf` gugur seluruhnya karena hilang di `s01` dan `s02`.
""")

code(r"""
# Seberapa mudah sesi dibedakan? Kalau sangat mudah, itu peringatan, bukan prestasi.
from sklearn.model_selection import cross_val_score, StratifiedKFold

y_sess = Dp["session"].to_numpy()
clf = RandomForestClassifier(n_estimators=200, random_state=0, n_jobs=-1)
acc = cross_val_score(clf, X, y_sess, cv=StratifiedKFold(5, shuffle=True,
                                                         random_state=0)).mean()
print(f"akurasi menebak SESI dari fitur CSI: {acc:.1%}  (acak = {1/len(set(y_sess)):.1%})")
print("\nAngka tinggi di sini BUKAN kabar baik: artinya tiap sesi punya sidik jari")
print("kanal sendiri. Model jumlah orang yang dilatih lintas sesi bisa mendapat")
print("akurasi tinggi hanya dengan mengenali sesi, lalu menyebut okupansi sesi itu.")
""")

# ---------------------------------------------------------------- tahap 7
md(r"""
---
## 7. Zona A/B/C/D

Penempatan board dikonfirmasi pengguna 2026-09-14:

| Zona | Board |
|---|---|
| A | `d0` |
| B | `bf` |
| C | `38` |
| D | `4b` |

> **Berbeda dari `COUNTING_RUNBOOK.md`.** Runbook menulis A=`38` dan C=`d0` —
> tertukar dibanding angka di atas. B dan D sama. Yang dipakai di sini adalah
> angka pengguna: runbook itu rencana, pengguna yang mengukur ruangan
> sebenarnya. Data tidak bisa menengahi perselisihan ini (lihat sel terakhir
> bagian ini), jadi kalau nanti ternyata runbook yang benar, cukup ubah
> `ZONE_BOARD` di `loader.py` lalu jalankan ulang notebook.

Pertanyaan bagian ini: **apakah board di zona X lebih terpengaruh oleh orang di
zona X daripada oleh orang di zona lain?** Kalau ya, penghitungan per zona
menjadi mungkin dan tiap board bisa dipakai sebagai sensor lokal.
""")

code(r"""
zone_tot = {}
for s in SESSIONS:
    occ = occ_all[s]
    zone_tot[s] = {z: float((occ[z] * occ["dur"]).sum() / occ["dur"].sum())
                   for z in ZONES}
zt = pd.DataFrame(zone_tot).T.round(2)
zt["total"] = zt.sum(axis=1).round(2)
print("Rata-rata jumlah orang per zona (berbobot durasi):")
print(zt.to_string())

fig, ax = plt.subplots(figsize=(8.5, 3.2))
zt[ZONES].plot(kind="bar", stacked=True, ax=ax, colormap="Set2")
ax.set_ylabel("rata-rata orang"); ax.set_xlabel("")
ax.set_xticklabels([s.replace("count_", "") for s in zt.index], rotation=0)
ax.set_title("Sebaran orang per zona tiap sesi")
ax.legend(title="zona", ncol=4, fontsize=8)
plt.tight_layout(); plt.savefig(f"{FIGDIR}/13_zone_distribution.png"); plt.show()

print("\nrata-rata seluruh sesi berpenghuni:")
print(zt.drop(index="count_s10")[ZONES].mean().round(2).to_string())
""")

md(r"""
**Zona B praktis tidak pernah terisi.** Rata-ratanya 0.0–0.6 orang di setiap
sesi, dan di `count_s07` tepat nol sepanjang rekaman. Orang terkonsentrasi di
zona C dan D.

Akibatnya langsung: board `bf` (zona B) **tidak punya sinyal zona untuk
dipelajari**. Analisis per zona di bawah karena itu praktis hanya menyentuh
A, C, dan D — dan bahkan A hanya bergerak antara 1 dan 4 orang.
""")

code(r"""
# Korelasi statistik tiap board terhadap hitungan tiap zona.
#
# DIPUSATKAN PER SESI lebih dulu. Tanpa itu, korelasi apa pun hanya akan
# mencerminkan bahwa sesi dengan banyak orang di D juga sesi dengan sidik jari
# kanal tertentu -- persis kekeliruan yang dibongkar di Bagian 5.
Wz = D_all.copy()
for c in feat_cols + ZONES:
    Wz[c] = Wz[c] - Wz.groupby("session")[c].transform("mean")

def zone_corr(stat):
    m = pd.DataFrame(index=["38", "4b", "bf", "d0"], columns=ZONES, dtype=float)
    for b in m.index:
        c = f"{b}_{stat}"
        if c not in Wz.columns:
            continue
        for z in ZONES:
            sub = Wz[[c, z]].dropna()
            if len(sub) > 30 and sub[z].std() > 0:
                m.loc[b, z] = sub[c].corr(sub[z], method="spearman")
    return m

fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
for ax, stat in zip(axes, ["amp_mean", "rssi_std", "sub_var"]):
    m = zone_corr(stat)
    im = ax.imshow(m.to_numpy(dtype=float), cmap="RdBu_r", vmin=-0.25, vmax=0.25)
    ax.set_xticks(range(4)); ax.set_xticklabels(ZONES)
    ax.set_yticks(range(4)); ax.set_yticklabels(m.index)
    ax.set_xlabel("zona (jumlah orang)"); ax.set_ylabel("board")
    ax.set_title(stat, fontsize=9); ax.grid(False)
    for i, b in enumerate(m.index):
        for j, z in enumerate(ZONES):
            v = m.loc[b, z]
            if pd.isna(v):
                continue
            match = loader.ZONE_BOARD[z] == b
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=8,
                    fontweight="bold" if match else "normal", color="black")
            if match:
                ax.add_patch(plt.Rectangle((j - .5, i - .5), 1, 1, fill=False,
                                           edgecolor="lime", lw=2.5))
    plt.colorbar(im, ax=ax, fraction=0.046)
plt.suptitle("Korelasi dalam-sesi: statistik board vs jumlah orang per zona\n"
             "(kotak hijau = pasangan board-zona menurut denah)")
plt.tight_layout(rect=[0, 0, 1, 0.90])
plt.savefig(f"{FIGDIR}/16_zone_coupling.png", bbox_inches="tight"); plt.show()
""")

code(r"""
# Uji tegas: apakah pasangan board-zona yang COCOK punya korelasi lebih tinggi
# daripada pasangan yang tidak cocok? Kalau ya, ada kopling spasial.
rows = []
biggest = 0.0
for stat in loader.STATS:
    m = zone_corr(stat)
    arr = m.to_numpy(dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr):
        biggest = max(biggest, float(np.abs(arr).max()))
    match, other = [], []
    for b in m.index:
        for z in ZONES:
            v = m.loc[b, z]
            if pd.isna(v):
                continue
            (match if loader.ZONE_BOARD[z] == b else other).append(abs(v))
    if match and other:
        rows.append({"stat": stat,
                     "cocok_mean": round(np.mean(match), 3),
                     "tak_cocok_mean": round(np.mean(other), 3),
                     "selisih": round(np.mean(match) - np.mean(other), 3),
                     "n_cocok": len(match)})
zc = pd.DataFrame(rows)
print(zc.to_string(index=False))
print(f"\nstatistik di mana pasangan cocok LEBIH kuat: "
      f"{(zc['selisih'] > 0).sum()} dari {len(zc)}")
print(f"korelasi terbesar yang pernah muncul (pasangan mana pun): {biggest:.3f}")
""")

md(r"""
**Hasilnya: kopling board–zona tidak terdeteksi.** Semua korelasi berada di
bawah |r| ≈ 0.18, dan pasangan yang "cocok" menurut denah tidak secara konsisten
lebih kuat daripada pasangan yang tidak cocok.

Ini **bukan** bukti bahwa denahnya salah, dan bukan bukti bahwa metodenya gagal.
Penyebabnya lebih sederhana, dan sudah muncul berulang sepanjang notebook ini:
di dalam satu sesi, jumlah orang per zona nyaris tidak pernah berubah. Tidak ada
variasi yang bisa dikorelasikan. Zona B bahkan tidak pernah terisi sama sekali.

Untuk menguji kopling spasial secara sungguhan dibutuhkan sesi yang dirancang
khusus: **satu orang berpindah dari zona ke zona, berhenti ~60 detik di tiap
zona, sementara zona lain dikosongkan.** Satu sesi seperti itu akan memberi
jawaban yang jelas — sesuatu yang sepuluh sesi sekarang tidak bisa.
""")

code(r"""
# Karena kopling lemah, data TIDAK bisa menengahi denah pengguna vs runbook.
# Sel ini menunjukkannya apa adanya, supaya tidak ada yang mengira pemetaan
# bisa "ditemukan" dari data ini.
RUNBOOK_MAP = {"A": "38", "B": "bf", "C": "d0", "D": "4b"}

rows = []
for stat in loader.STATS:
    m = zone_corr(stat)

    def mean_matched(mp):
        v = [abs(m.loc[b, z]) for z, b in mp.items()
             if b in m.index and not pd.isna(m.loc[b, z])]
        return np.mean(v) if v else np.nan

    rows.append({"stat": stat,
                 "denah_pengguna": round(mean_matched(loader.ZONE_BOARD), 3),
                 "denah_runbook": round(mean_matched(RUNBOOK_MAP), 3)})
cmp_map = pd.DataFrame(rows)
cmp_map["selisih"] = (cmp_map["denah_pengguna"] - cmp_map["denah_runbook"]).round(3)
print(cmp_map.to_string(index=False))
print(f"\ndenah pengguna lebih cocok di {(cmp_map['selisih'] > 0).sum()} "
      f"dari {len(cmp_map)} statistik")
print("\nSelisih sekecil ini jauh di bawah derau: data TIDAK bisa memastikan")
print("denah mana yang benar. Pakai pengukuran fisik ruangan, bukan angka ini.")
""")

# ---------------------------------------------------------------- tahap 8
md(r"""
---
## 8. Kesimpulan

### Yang sehat di data ini

- **Transport dan waktu.** 39 file `.bin` terbaca utuh, seluruhnya `sig_len=114`,
  satu AP, satu kanal. Laju ~36–44 paket/detik per board sesuai harapan.
- **Sinyalnya kaya.** 256 subcarrier (244 aktif) per paket, jauh lebih rinci
  daripada kerja lokalisasi sebelumnya di proyek ini.
- **Pelabelnya presisi.** `occupancy.csv` dan `occupancy_events.csv` mencatat
  waktu dengan resolusi milidetik dan rinci per zona.
- **Ada baseline ruangan kosong.** `count_s10` (290 detik, 4 board, nol event)
  — ini yang paling mengubah keadaan dibanding versi pertama notebook.

### Yang membatasi, dan seberapa jauh

| Temuan | Akibat |
|---|---|
| Hanya SATU sesi kosong, direkam ~1 jam setelah yang lain | Efek "kosong" tercampur dengan hanyutan kanal; butuh beberapa sesi kosong di waktu berbeda |
| Okupansi hampir konstan per sesi | Ukuran sampel efektif ≈ jumlah transisi (belasan), bukan jumlah jendela (ribuan) |
| Label melompat 0 lalu 7–16 | Yang tersedia dua rezim (kosong/penuh), bukan tangga bertingkat; regresi jumlah orang tak terlatih |
| `count_s07` nol transisi; `count_s09` semua event selesai di 20 detik pertama | Keduanya praktis satu kondisi konstan |
| `count_s01` (bf mati 11 s), `count_s02` (tanpa bf) | Efektif 3 board; fitur board `bf` gugur dari analisis lintas-sesi |
| Sesi mudah dikenali dari CSI | Model lintas sesi bisa berakurasi tinggi tanpa benar-benar menghitung orang |
| Zona B hampir selalu kosong (0.0–0.6 orang) | Board `bf` tak punya sinyal zona untuk dipelajari; analisis zona praktis hanya A/C/D |
| Isi tiap zona hampir tak berubah dalam satu sesi | Kopling board–zona tidak terdeteksi (semua \|r\| < 0.18) |

### Jawaban atas pertanyaan notebook

**Apakah CSI bereaksi terhadap perubahan okupansi? Sedikit, dan hanya lewat
fitur tertentu.**

Dari 18 kombinasi (6 statistik × 3 lebar jendela) yang diuji terhadap pembanding
waktu acak:

| Fitur | Hasil |
|---|---|
| `rssi_std` (8 s, 15 s) | **p < 0.0001** — respons di transisi jelas lebih besar, di dua skala waktu |
| `amp_std` (4 s) | p = 0.0001, tapi hilang saat jendela diperlebar |
| `sub_var`, `sub_std_spatial` | mendekati ambang (p ≈ 0.07), tidak pernah lewat |
| `amp_mean`, `rssi_mean` (semua) | **tidak pernah** signifikan |

Hanya **3 dari 18 kombinasi** yang signifikan.

Polanya konsisten dengan temuan proyek ini sebelumnya: yang membawa informasi
adalah ukuran **sebaran** (std, variance), bukan ukuran **level** (rata-rata).
Amplitudo rata-rata praktis buta terhadap okupansi.

Besarnya efek tetap kecil — wajar, karena tiap transisi hanya memindahkan ~1
dari 16 orang (~6%). Jangan menuliskannya sebagai "CSI tidak bereaksi";
tuliskan sebagai: respons terhadap perpindahan satu orang hanya terdeteksi lewat
fitur berbasis sebaran dan tidak konsisten lintas skala waktu.

### Angka yang paling perlu diingat: 96.6%

Random forest bisa menebak **sesi mana** sebuah jendela berasal dengan akurasi
96.4% (acak = 12.5%). Tiap sesi punya sidik jari kanal sendiri. Karena tiap sesi
juga punya okupansi yang praktis konstan, model jumlah orang yang dilatih lintas
sesi bisa mencapai akurasi tinggi **semata-mata dengan mengenali sesi** lalu
menyebutkan okupansi sesi itu — tanpa pernah benar-benar menghitung orang.

Bukti pendukungnya di Bagian 5: median |korelasi| fitur terhadap jumlah orang
turun dari **0.347 menjadi 0.047** begitu efek sesi dibuang — menyusut 7 kali
lipat — dan 20 dari 24 fitur kehilangan lebih dari separuh korelasinya.

### Zona: belum terjawab, dan alasannya sama

Dengan denah board diketahui (A=`d0`, B=`bf`, C=`38`, D=`4b`), Bagian 7 menguji
apakah tiap board lebih peka terhadap zonanya sendiri. **Tidak terdeteksi:**
semua korelasi board–zona di bawah |r| ≈ 0.18, dan pasangan yang cocok menurut
denah tidak konsisten lebih kuat daripada yang tidak cocok.

Penyebabnya bukan denah yang salah dan bukan metode yang gagal, melainkan hal
yang sama yang menghalangi penghitungan: **isi tiap zona nyaris tidak pernah
berubah di dalam satu sesi.** Zona B bahkan tidak pernah terisi sama sekali
(rata-rata 0.0–0.6 orang di seluruh sepuluh sesi).

Data juga **tidak bisa menengahi** perbedaan denah pengguna vs
`COUNTING_RUNBOOK.md` (yang menukar A dan C): selisih kecocokannya jauh di bawah
derau. Pakai pengukuran fisik ruangan, bukan angka dari data ini.

### Rekomendasi

Data ini sekarang mendukung **deteksi okupansi** (ada orang / tidak ada orang)
sebagai temuan yang bisa dilaporkan, dengan catatan satu sesi kosong. Data ini
**belum** mendukung **penghitungan** jumlah orang — untuk itu keragaman
okupansinya masih terlalu sedikit.

Yang paling menambah nilai, berurutan:

1. **Dua sampai tiga sesi kosong lagi, di waktu berbeda** (mis. pagi, siang,
   sore). Ini yang mengubah temuan Bagian 4b dari indikatif menjadi kokoh, karena
   memisahkan "kosong" dari "kondisi kanal jam sekian". Paling murah, paling
   menentukan.
2. **Sesi bertingkat 0 -> 16 orang**, berhenti ~60 detik di tiap tingkat. Tanpa
   ini tidak ada satu pun titik data di antara 1 dan 6 orang, sehingga regresi
   jumlah orang tak punya apa pun untuk dipelajari di rentang itu.
3. **Ulangi di hari berbeda.** Satu-satunya cara mengetahui apakah model
   menghitung orang atau menghafal kondisi kanal hari itu.
4. **Perbaiki board `bf`** sebelum sesi berikutnya, dan pastikan keempat board
   terlihat di kolektor sebelum mulai.
5. **Sesi khusus kopling zona**: satu orang berpindah zona demi zona, berhenti
   ~60 detik di tiap zona, zona lain dikosongkan. Ini yang akan menjawab
   pertanyaan Bagian 7 — dan sekaligus memastikan denah board benar.

Sementara itu, kalau perlu hasil dari data yang ada:

- **Untuk deteksi okupansi**: laporkan ukuran efek kosong-vs-penuh dari
  Bagian 4b, sebutkan terus terang bahwa sesi kosongnya hanya satu.
- **Untuk penghitungan**: pakai `count_s03` dan `count_s05` (variasi okupansi
  paling lama), evaluasi dengan sesi sebagai grup, dan laporkan sebagai
  *studi kelayakan*, bukan sebagai penghitung orang yang berfungsi.
""")
