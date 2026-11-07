# RUNBOOK — Uji lokalisasi 4 sudut (dipakai saat OFFLINE)

Prosedur capture untuk tes lokalisasi kasar: **di kuadran mana orang berada?**
Semua perintah bisa disalin apa adanya. Tidak butuh internet.

Baca `RUNBOOK.md` dulu untuk prosedur dasar (pindah jaringan, cek IP, flash).
Dokumen ini hanya menambahkan bagian khusus lokalisasi.

---

## Denah dan urutan jalan

```
              9 m
   38 ──────────────────── bf          38 = kiri-atas
   │                       │           bf = kanan-atas
   │                       │           d0 = kiri-bawah
   │          R            │  7 m      4b = kanan-bawah
   │       (router)        │           R  = router, di TENGAH
   │                       │
   d0 ──────────────────── 4b
```

**Urutan jalan: `4b` -> `bf` -> `38` -> `d0` -> kembali ke `4b`.**

Radius jalan **2–2.5 m dari router**. Jangan menempel dinding (nanti posisi
berada di LUAR ruas router->board, gangguannya melemah) dan jangan mengitari
router terlalu rapat (keempat jalur terganggu sekaligus).

> **Yang sebenarnya diukur.** Tiap board mengukur kanal `router -> board`.
> Orang mengganggu sebuah board saat MEMOTONG garis itu, bukan saat berdiri
> dekat board-nya. Jadi yang dipulihkan adalah ARAH dari router, bukan jarak.
> Itu batas metode, bukan kegagalan — tulis apa adanya di skripsi.

---

## Tiga capture, tiga folder terpisah

**SATU SESI = SATU FOLDER.** Kolektor tidak menghapus isi folder lama; kalau
dua sesi tercampur, angka yang keluar salah tapi kelihatan masuk akal.

| Folder | Isi | Durasi |
|---|---|---|
| `capture/loc_baseline` | Ruangan KOSONG, tidak ada orang | ~2 menit |
| `capture/loc_static` | Diam 30 s di tiap sudut, urut 4b→bf→38→d0 | ~2,5 menit |
| `capture/loc_walk` | Jalan memutar 8 lap × 40 s | ~5,5 menit |

Ketiganya wajib. `loc_baseline` menentukan skala tiap board; `loc_static`
menentukan **polaritas** (amplitudo naik atau turun saat jalur terhalang) —
tanpa itu hasil bisa terbalik dan tidak ada cara mengetahuinya.

---

## Persiapan sekali di awal

1. Pasang keempat board di sudut, **tinggi seragam** (mis. semua 1 m dari
   lantai). Beda tinggi mengubah geometri jalur dan mencemari perbandingan
   antar board.
2. Router di tengah ruangan, tidak dipindah sama sekali sampai ketiga capture
   selesai. **Kalau router bergeser, ketiga capture harus diulang.**
3. Siapkan metronom di HP. Hitung langkah per lap sekali, lalu pertahankan.
   Contoh: keliling lingkaran radius 2,25 m ≈ 14 m; kalau 1 langkah ≈ 0,6 m,
   itu ≈ 24 langkah per lap. Untuk 40 s per lap → 24 langkah / 40 s = **36 BPM**
   (atau 72 BPM dengan satu langkah tiap dua ketuk, lebih nyaman diikuti).
4. Tandai keempat sudut lintasan di lantai (lakban) supaya lintasan tiap lap
   sama.

---

## Capture 1 — Ruangan kosong (~2 menit)

Kolektor DULU, board KEMUDIAN. Keempat board harus hidup bersamaan.

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2
python tools\csi_collector.py --outdir capture\loc_baseline --duration 120 -v
```

**Keluar dari ruangan** dan tutup pintu. Jangan ada yang bergerak sampai
kolektor berhenti sendiri setelah 120 detik.

> Ini capture terpenting sekaligus yang paling mudah dirusak. Satu orang lewat
> di depan pintu sudah cukup untuk menggeser median. Kalau ragu, ulangi.

---

## Capture 2 — Statik per sudut (~2,5 menit)

```powershell
python tools\csi_collector.py --outdir capture\loc_static --duration 150 -v
```

Setelah kolektor jalan, masuk ruangan dan **berdiri diam 30 detik** di tiap
sudut lintasan, urut:

```
4b (kanan-bawah)  ->  bf (kanan-atas)  ->  38 (kiri-atas)  ->  d0 (kiri-bawah)
```

Pakai stopwatch. Berpindah antar sudut secepatnya (skrip membuang 20% di tiap
ujung segmen, jadi transisi tidak ikut terhitung).

Berdiri di **titik lintasan** dekat sudut itu (radius 2–2,5 m dari router),
bukan menempel di board.

---

## Capture 3 — Jalan memutar (~5,5 menit)

Butuh **tiga terminal**.

Terminal #1 — kolektor:

```powershell
python tools\csi_collector.py --outdir capture\loc_walk --duration 330 -v
```

Terminal #2 — pencatat penanda (jalankan tepat sebelum mulai jalan):

```powershell
python tools\mark_events.py --outdir capture\loc_walk
```

Lalu: nyalakan metronom, mulai di sudut `4b`, jalan searah urutan di atas,
**tekan ENTER tiap kali melewati sudut**. Laptop dibawa (atau pakai keyboard
nirkabel); kalau tidak memungkinkan, minta bantuan orang kedua yang duduk diam
di luar lintasan.

8 lap × 40 s = 320 detik. Ctrl-C di terminal #2 setelah selesai.

> **Kalau tidak ada yang bisa menekan Enter:** jalankan tanpa penanda, catat
> jam mulai dan detik per lap di kertas. Analisis tetap jalan (lihat bagian
> "Tanpa penanda"), tapi tempo yang melenceng tidak terkoreksi.

---

## Cek hasil (masih offline, tidak butuh internet)

**Langkah 1 — kesehatan capture.** Untuk ketiga folder:

```powershell
python tools\csi_merge.py capture\loc_baseline --stats-only
python tools\csi_merge.py capture\loc_static   --stats-only
python tools\csi_merge.py capture\loc_walk     --stats-only
```

Yang dilihat: **4 node**, `hilang` kecil, dan bin berisi semua node **>90%**.
Kalau salah satu jauh di bawah itu, capture-nya bermasalah — ulangi sebelum
lanjut menganalisis.

**Langkah 2 — polaritas dari capture statik.** Ini penentunya:

```powershell
python tools\localize_baseline.py capture\loc_static --baseline capture\loc_baseline --static-mode --plot static.png
```

Keluaran yang diharapkan, per board:

```
  node 4b (kanan-bawah): z_sendiri=-3.21 z_lain=+0.12 -> shadowing (turun)
```

**Yang menentukan sehat atau tidak:**

| Cek | Sehat | Artinya kalau tidak |
|---|---|---|
| `z_sendiri` vs `z_lain` | beda jelas (>1σ) | Sudut itu tidak terpisahkan; cek posisi board |
| Akurasi TOTAL | jauh di atas 25% | Sinyalnya belum cukup — lihat tabel masalah |
| Arah polaritas | boleh apa saja | Campur (sebagian naik, sebagian turun) itu WAJAR |

> Polaritas campur antar board bukan kesalahan. Tiap jalur punya geometri
> multipath sendiri; yang penting konsisten untuk board yang sama.

**Langkah 3 — analisis jalan memutar:**

```powershell
python tools\localize_baseline.py capture\loc_walk --baseline capture\loc_baseline --static capture\loc_static --markers capture\loc_walk\markers.csv --plot walk.png
```

### Tanpa penanda

```powershell
python tools\localize_baseline.py capture\loc_walk --baseline capture\loc_baseline --static capture\loc_static --plot walk.png
```

Tanpa `--markers` tidak ada confusion matrix, tapi plot dan sebaran prediksi
tetap keluar. Kalau keempat sudut masing-masing dapat ~25% dan plotnya
memperlihatkan pola berputar yang berulang 8 kali, itu sudah bukti kuat
meskipun tanpa label.

---

## Membaca hasilnya

Di `walk.png`, panel tengah ("skor terarah") adalah yang paling informatif:
kalau metodenya bekerja, keempat kurva bergantian memuncak dengan beda fase
seperempat lap, dan polanya berulang 8 kali.

| Akurasi TOTAL | Tafsiran |
|---|---|
| >70% | Bagus. Lokalisasi kuadran jelas terbaca dari CSI. |
| 40–70% | Sinyal ada tapi berisik. Lihat confusion: biasanya sudut bersebelahan yang tertukar — itu wajar, batas kuadran memang kabur. |
| 25–40% | Lemah. Cek dulu apakah `loc_baseline` benar-benar kosong. |
| <25% | Di bawah tebakan acak — hampir pasti polaritas terbalik atau baseline tercemar, BUKAN "CSI tidak bisa". |

Sudut yang tertukar dengan **tetangganya** normal. Sudut yang tertukar dengan
sudut **seberang** (4b↔38 atau bf↔d0) itu mencurigakan — biasanya berarti
baseline tercemar atau ada board yang bergeser di tengah sesi.

### Opsi penyetelan

| Masalah | Coba |
|---|---|
| Prediksi terlalu meloncat-loncat | `--smooth 2.0` (default 1.0 detik) |
| Transisi tampak tertinggal | `--smooth 0.5` |
| Board tidak semuanya ada | `--order 4b,bf,38` (board yang mati dikeluarkan) |
| Segmen statik tidak 30 s | `--dwell-s 20` |

---

## Kalau ada masalah

| Gejala | Kemungkinan penyebab | Tindakan |
|---|---|---|
| `tidak ada bin yang berisi keempat node` | Board tidak hidup bersamaan | Cek `--stats-only`; semua board harus menyala serentak |
| `node hilang di ...` | Satu board mati/tidak connect | Cek monitor board itu; ulangi capture |
| `! MAD=0` | Baseline terlalu pendek atau board diam total | Perpanjang baseline jadi 3 menit |
| Satu board selalu menang | Baselinenya tidak mewakili | Ulangi `loc_baseline`; pastikan ruangan benar-benar kosong |
| Akurasi ~25% persis | Tidak ada sinyal sama sekali | Cek apakah ketiga capture memang dari penempatan board yang SAMA |
| Penanda tidak beririsan | `markers.csv` dari sesi lain | Penanda harus dari folder yang sama dengan `.bin`-nya |

---

## Yang perlu dilaporkan setelah kembali online

1. Keluaran `--stats-only` untuk ketiga folder
2. Keluaran lengkap langkah 2 (polaritas) dan langkah 3 (confusion matrix)
3. `static.png` dan `walk.png`
4. Catatan lapangan: detik per lap sebenarnya, dan apa pun yang tidak sesuai
   rencana (ada orang lewat, board bergeser, tempo melenceng)

Data `.bin` tetap tersimpan — semua analisis bisa diulang tanpa capture ulang.
