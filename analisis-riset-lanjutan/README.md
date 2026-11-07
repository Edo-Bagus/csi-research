# Analisis riset lanjutan: okupansi kelas dan lokalisasi

[English version](README.en.md)

Kode dan hasil analisis Channel State Information (CSI) Wi-Fi dari empat ESP32-C6 dan satu router. Folder ini memuat dua analisis: deteksi okupansi di dua ruang kelas, dan lokalisasi kuadran pada satu sesi.

Riset ini tidak selesai. Kehadiran orang terdeteksi, tapi jumlah orang dan isi tiap zona belum terjawab.

## Status

| Pertanyaan | Hasil | Batasnya |
|---|---|---|
| Kosong atau berpenghuni | Koherensi temporal memisahkan 19 sesi tanpa tumpang-tindih | Hanya 2 sesi kosong, satu per ruangan |
| Berapa orang | Belum terjawab | Koherensi tidak berkaitan dengan jumlah orang |
| Zona mana yang terisi | Belum terjawab | Denah sebenarnya tidak mengungguli permutasi lain |
| Di kuadran mana satu orang berjalan | 89,9%, leave-one-lap-out | Satu orang, satu sesi, 8 lap |

| Bagian | Bisa dijalankan |
|---|---|
| Tes tanpa data mentah | Ya, langsung |
| Tes penuh, tiga analisis, dua notebook | Ya, setelah file `.bin` dikembalikan |

## Isi folder

```text
analisis-riset-lanjutan/
├── tools/
│   ├── csi_merge.py               Pembaca frame .bin, dipakai kedua analisis
│   └── localize_baseline.py       Aturan argmax tangan, pembanding lokalisasi
├── ml_people_count/
│   ├── src/csi_occupancy/         Paket analisis okupansi
│   ├── tests/                     25 tes
│   ├── notebooks/                 Notebook ruangan 1, tersimpan tanpa keluaran
│   ├── results/                   Gambar dan tabel hasil
│   ├── data/raw/                  Label okupansi tiap sesi, tanpa .bin
│   └── README.md                  Catatan asli
└── ml_localization/
    ├── features.py                Ekstraksi fitur
    ├── localization_ml.ipynb      Notebook utama, tersimpan dengan keluaran
    ├── figures/                   Gambar hasil
    ├── data/loc_walk/markers.csv  Penanda lap
    └── README.md                  Catatan asli
```

Semua kode, hasil, dan label disalin tanpa perubahan. `static.png` dan `walk.png` dipindah dari root folder riset asli ke `ml_localization/figures/`. File `.bin`, cache fitur, dan model terlatih tidak disertakan.

`tools/` harus tetap sejajar dengan `ml_people_count/` dan `ml_localization/`, karena kedua analisis mengimpor `read_bin` dari `../tools/csi_merge.py`.

## Alur

```text
.bin tiap board ──> read_bin ──┬──> csi_occupancy: jendela, label, koherensi, kontrol null
                               └──> features.py: jendela 500 ms, normalisasi, model kuadran
```

## Data

| Dataset | Tanggal | Lokasi | Sesi | File `.bin` | Sesi kosong |
|---|---|---|---|---|---|
| `data-14-9` | 2026-09-14 | Ruang kelas 1, kelas 7–16 orang | 10 | 39 | `count_s10` |
| `data-15-9` | 2026-09-15 | Ruang kelas 2, kelas 45–72 orang | 9 | 36 | `count_2_9` |
| `loc_baseline`, `loc_static`, `loc_walk` | 2026-09-09 | Tidak tercatat | 3 | 12 | `loc_baseline` |

Dua dataset pertama direkam di kelas yang sedang berlangsung, jadi subjeknya mahasiswa yang sedang kuliah. Protokol yang mengandaikan kendali atas orang tidak berlaku di sini.

### Denah zona

Router berada di tengah ruangan, dan board di tiap sudut.

| Zona | Posisi | Ruangan 1 | Ruangan 2 |
|---|---|---|---|
| A | Kiri atas | `d0` | `d0` |
| B | Kanan atas | `bf` | `bf` |
| C | Kiri bawah | `38` | `4b` |
| D | Kanan bawah | `4b` | `38` |

Rekaman `loc_*` memakai denah lain: `38` kiri atas, `bf` kanan atas, `d0` kiri bawah, dan `4b` kanan bawah.

Frame `.bin` tidak menyimpan denah, dan data tidak bisa menengahi kalau catatannya salah. Denah ruangan ada di `zone_board` pada `src/csi_occupancy/datasets.py`.

### Mengembalikan file `.bin`

Data mentah Fase 3 belum diterbitkan. File `.bin` berada di folder riset asli, `esp/RISET_CSI_2/`, dengan total sekitar 1,5 GB. Salin ke jalur yang sama di sini:

```text
ml_people_count/data/raw/<dataset>/<sesi>/*.bin
ml_localization/data/loc_baseline/*.bin
ml_localization/data/loc_static/*.bin
ml_localization/data/loc_walk/*.bin
```

Salin dari `ml_people_count/data/raw/` dan `ml_localization/data/` di folder asli, bukan dari `capture/`. `capture/count_s09` punya 4 file kecil tambahan, dan `load_session` hanya menyimpan satu file per board, jadi file itu akan menimpa rekaman utama.

Nama file dan isi frame memuat MAC board dan BSSID router. Perhatikan ini kalau data kelak diterbitkan.

## Kebutuhan

- Python 3.12.2
- Paket di `ml_people_count/requirements.txt`, ditambah pytest
- Untuk lokalisasi: xgboost dan Jupyter

```bash
pip install -r ml_people_count/requirements.txt pytest xgboost==3.2.0 jupyter
```

## Menjalankan

### Okupansi

Jalankan dari folder `ml_people_count`, dan arahkan Python ke paket di folder ini.

```powershell
cd ml_people_count
$env:PYTHONPATH = "src"
```

Pastikan path yang tercetak berada di folder ini.

```bash
python -c "import csi_occupancy; print(csi_occupancy.__file__)"
```

Di komputer riset, `csi_occupancy` masih terpasang dari folder asli. Tanpa `PYTHONPATH`, perintah berikut memakai kode asli dan menulis hasil ke sana.

Tanpa data mentah:

```bash
python -m pytest tests -m "not needs_data"
```

Hasil yang diharapkan: 17 tes lolos. Tanpa filter ini, 8 tes yang butuh data akan gagal, bukan dilewati.

Dengan data mentah:

```bash
python -m pytest tests
```

```bash
python -m csi_occupancy.eda_windows
```

```bash
python -m csi_occupancy.session_level
```

```bash
python -m csi_occupancy.coherence
```

Jalan pertama butuh sekitar 5 menit. Cache fitur masuk ke `data/processed/`, dan tabel hasil masuk ke `results/tables/`.

### Lokalisasi

```bash
cd ml_localization
```

```bash
jupyter notebook localization_ml.ipynb
```

Pilih Run All. Jalan pertama butuh sekitar 5 menit. Notebook membuat `cache/` dan `model_extra_trees.joblib`, dan menimpa isi `figures/`.

## Hasil pengujian ulang

Semua perintah di atas dijalankan pada 2026-11-07 dari salinan folder ini dengan file `.bin` dikembalikan. Versi yang dipakai: Python 3.12.2, numpy 2.3.5, pandas 2.3.3, scipy 1.16.3, scikit-learn 1.8.0, matplotlib 3.10.8, xgboost 3.2.0.

| Pemeriksaan | Hasil |
|---|---|
| Tes dengan data mentah | 25 lolos |
| `results/tables/coherence_summary.csv` | Identik byte per byte dengan hasil lama |
| Keluaran `eda_windows` dan `session_level` | Cocok dengan `ml_people_count/README.md` |
| `eda_people_count.ipynb` | Berjalan tanpa error, angka ruangan 1 cocok |
| `localization_ml.ipynb` | Keluaran teks sama dengan yang tersimpan, kecuali log cache |

Beberapa angka di `ml_people_count/README.md` tidak dicetak oleh kode di folder ini, jadi tidak bisa diuji ulang:

- Fitur level per sesi: rho −0,92 dan −0,90, lalu −0,36 dan −0,31 setelah kontrol jam.
- Respons per board: `bf` +0,73 dan `d0` −0,51 di ruangan 2.

## Hasil

### Koherensi temporal

Koherensi adalah autokorelasi amplitudo per subcarrier, dirata-rata atas subcarrier aktif. Sumbernya `python -m csi_occupancy.coherence`.

| Lag | Ruangan 1 kosong | Ruangan 1, 16 orang | Ruangan 2 kosong | Ruangan 2, 72 orang |
|---|---|---|---|---|
| 1 paket | +0,07 | +0,56 | +0,16 | +0,68 |
| ±1 detik (40 paket) | +0,06 | +0,40 | +0,02 | +0,51 |
| ±5 detik (200 paket) | +0,02 | +0,24 | +0,01 | +0,35 |
| ±20 detik (800 paket) | +0,01 | +0,05 | −0,00 | +0,21 |

Koherensi pada ±1 detik:

- 17 sesi berpenghuni: 0,356–0,572, rata-rata 0,495.
- 2 sesi kosong: 0,146 dan 0,052.
- Mann-Whitney p = 0,0058, tanpa tumpang-tindih.

Di antara sesi berpenghuni, koherensi tidak berkaitan dengan jumlah orang: rho +0,16 di ruangan 1 dan −0,22 di ruangan 2, keduanya tidak signifikan.

### Kontrol null

Beberapa hasil tampak positif dengan ukuran biasa, lalu runtuh setelah dikontrol. Angka berikut dari ruangan 2.

| Uji | Hasil awal | Setelah kontrol |
|---|---|---|
| Deteksi, leave-one-session-out | Akurasi 0,933 | Sama dengan kelas mayoritas. `count_2_9` dapat 0,000 |
| Penghitungan antar-sesi | MAE 8,09 orang | Baseline rata-rata 9,37, simpangan label 10,7 |
| Penghitungan dalam sesi, `count_2_1` | MAE 4,10, baseline 5,69 | Null label-digeser dapat 3,64, jadi lebih mudah |
| Zona | Denah sebenarnya | Peringkat 8, 4, 3, dan 20 dari 24 permutasi |

### Lokalisasi kuadran

Protokolnya leave-one-lap-out dengan 456 jendela dan 169 fitur.

| Metode | Akurasi |
|---|---|
| Tebakan acak | 25,0% |
| Aturan `argmax` tangan | 79,4% |
| MLP | 84,6% |
| Logistic Regression | 85,5% |
| Random Forest | 89,3% |
| XGBoost | 89,7% |
| Extra Trees | 89,9% |

Kontrol label diacak mendapat 25,0%, dan label diacak dalam lap mendapat 24,2%. Yang terukur adalah arah dari router, bukan jarak. Angka ini berlaku untuk lap yang belum dilihat, bukan untuk hari, ruangan, atau orang lain.

## Aturan analisis

1. Jangan menggabung fitur dua ruangan. Laporkan hasil per ruangan.
2. Jangan membagi train dan test acak per jendela. Kelompokkan per sesi untuk okupansi, dan per lap untuk lokalisasi.
3. Klaim di dalam satu sesi harus mengalahkan null label-digeser-sirkuler.
4. Klaim klasifikasi harus dibandingkan dengan kelas mayoritas, dan dilihat per sesi.
5. Klaim tingkat sesi harus dikontrol terhadap jam mulai sesi.

## Langkah berikutnya

Kedua dataset punya cacat yang sama: satu sesi berisi satu tingkat okupansi yang nyaris konstan. Karena itu "kosong atau terisi" selalu menjadi perbandingan antar-sesi.

Rekaman yang paling berguna adalah satu perekaman tanpa putus melintasi bubarnya kelas, dari 10 menit sebelum kelas berakhir sampai 10 menit setelah ruangan kosong. Rekaman ini tidak butuh mengatur siapa pun.

## Hal yang perlu diketahui

- **README di dua subfolder adalah catatan asli.** Isinya tidak diubah. Perintah `cd` masih menunjuk folder asli, contoh `import loader` sudah digantikan `csi_occupancy.datasets`, dan rujukan ke `KNOWLEDGE.md` serta runbook menunjuk file yang tidak ikut di sini.
- **Laju paket mengikuti jumlah board.** Board yang sendirian mendapat 10 Hz, dan pada sesi empat board tiap board mendapat 27–46 Hz. Saat `bf` mati di `count_s01`, laju tiga board lain turun menjadi sekitar 3/4.
- **Board menangkap frame fisik yang sama.** Pada 5 sesi, 84–99,9% paket punya pasangan di board lain dalam ±100 µs menurut `timestamp` hardware. Kontrol dengan offset digeser 7,3 ms hanya mendapat 0,4–1,3%. Ini membantah docstring `tools/csi_merge.py` baris 8–11. Alamat tujuan frame tidak tersimpan, jadi dugaan bahwa frame itu balasan ping untuk board lain belum terbukti. Skrip pemeriksaan ini belum ada di folder ini.
- **Angka "244 subcarrier aktif" kurang tepat.** Indeks 0–2, 64, 126–130, dan 192 selalu nol. Sebanyak 242 indeks lain non-nol pada hampir semua paket, dan indeks 252–255 hanya non-nol pada 16–58% paket. Kedua analisis menghitung subcarrier aktif dari data, jadi hasilnya tidak terpengaruh. Letak indeks ini berbeda dari data skripsi.
- **Dua angka di catatan asli tidak cocok dengan keluarannya.** `ml_localization/README.md` menulis kontrol diacak dalam lap 25,2%, sedangkan notebook mencetak 24,2%. `ml_people_count/README.md` menulis kelas 52–72 orang di satu bagian, sedangkan data ruangan 2 mencakup 45–72.
- **`loc_static` tidak dipakai model.** Tidak ada `markers.csv` untuk rekaman ini, jadi label pada `figures/static.png` tidak bisa dipercaya.
- **Frame tidak punya version field.** Kalau format frame di firmware berubah, `tools/csi_merge.py` harus ikut berubah. Ketidakcocokan menghasilkan data yang terbaca tapi salah, bukan error.

## Asal kode

Kode disalin dari `esp/RISET_CSI_2/` di `CSI-PeopleCounting`. Firmware dan alat rekamnya ada di [firmware-riset-lanjutan](../firmware-riset-lanjutan/).
