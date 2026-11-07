# Riset CSI Wi-Fi pada ESP32-C6

[English version](README.en.md)

Firmware, alat rekam, kode analisis, dan hasil riset estimasi jumlah orang dan okupansi ruangan memakai Channel State Information (CSI) Wi-Fi 802.11ax pada ESP32-C6.

Riset ini terdiri dari tiga fase. Fase 1 dan 2 memakai data dan firmware yang sama. Fase 3 memakai sistem baru dan risetnya tidak selesai.

## Isi repo

| Folder | Isi | Fase | Status |
|---|---|---|---|
| [firmware-skripsi-conference](firmware-skripsi-conference/) | Firmware dua ESP32-C6 dan alat rekam UART | 1, 2 | Lengkap. Build bersih teruji, belum diuji ulang di perangkat |
| [training-skripsi-conference](training-skripsi-conference/) | Kode training dan hasil final | 1, 2 | Sebagian. Ekstraksi fitur dan training belum bisa dijalankan |
| [firmware-riset-lanjutan](firmware-riset-lanjutan/) | Firmware empat ESP32-C6, alat rekam TCP, rekaman | 3 | Sementara, belum dipilah. Build bersih teruji, belum diuji ulang di perangkat |
| [analisis-riset-lanjutan](analisis-riset-lanjutan/) | Analisis okupansi, lokalisasi, dan label | 3 | Lengkap. Hasilnya berhasil dijalankan ulang, tapi butuh file `.bin` |

Setiap folder punya README Indonesia dan Inggris, serta `.gitignore` sendiri.

## Tiga fase

| | Fase 1: Skripsi | Fase 2: Paper conference | Fase 3: Riset lanjutan |
|---|---|---|---|
| Perangkat | 2 ESP32-C6-DevKitC-1 | Sama dengan fase 1 | 4 ESP32-C6 dan router ASUS RT-AX53U |
| Sumber paket | ESP-NOW broadcast dari transmitter | Sama dengan fase 1 | Ping ke gateway, CSI dari frame router |
| Jalur data | UART (v2) ke PC lewat adapter USB-TTL | Sama dengan fase 1 | TCP ke laptop, tanpa kabel data |
| Lokasi | Ruangan 7 × 9 m, zona A dan B | Sama dengan fase 1 | Dua ruang kelas berbeda |
| Subjek | Peneliti dan 5 relawan | Sama dengan fase 1 | Mahasiswa yang sedang kuliah |
| Pertanyaan | Berapa orang, 0 sampai 6 | Sama, ditambah uji signifikansi tingkat rekaman | Apakah okupansi kelas nyata bisa dideteksi tanpa mengatur orang |

Fase 1 dan 2 punya naskah:

- Skripsi: *Studi Komparatif Model Machine Learning untuk Penghitungan Jumlah Orang dalam Ruangan Berbasis Channel State Information (CSI) Wi-Fi 802.11ax pada Perangkat ESP32-C6*.
- Paper: *Comparative Study of Machine Learning Models for Indoor People Counting Based on Wi-Fi 802.11ax Channel State Information (CSI) on ESP32-C6*.

## Alur

```text
Fase 1, 2   firmware-skripsi-conference ──> dataset Zenodo ──> training-skripsi-conference

Fase 3      firmware-riset-lanjutan ──> capture/ ──> analisis-riset-lanjutan
```

## Hasil ringkas

### Fase 1 dan 2

Nilai berikut adalah rata-rata dan simpangan baku dari 4 outer fold.

| Tugas | Model terbaik | Hasil |
|---|---|---|
| Klasifikasi, fitur magnitudo | 1D CNN | Akurasi 0,936 ± 0,030, F1-macro 0,944 ± 0,030 |
| Regresi | CNN-LSTM | MAE 0,243 ± 0,062, R² 0,934 ± 0,031 |

Setiap label hanya berasal dari satu kelompok file rekaman, dan kondisi radio tiap label berbeda. Jadi angka ini belum memisahkan pengaruh jumlah orang dari pengaruh sesi rekam.

### Fase 3

| Pertanyaan | Hasil |
|---|---|
| Kosong atau berpenghuni | Koherensi temporal memisahkan 19 sesi tanpa tumpang-tindih, dengan hanya 2 sesi kosong |
| Berapa orang | Belum terjawab |
| Zona mana yang terisi | Belum terjawab |
| Di kuadran mana satu orang berjalan | 89,9% pada satu sesi dengan satu orang |

## Data

| Data | Lokasi | Status |
|---|---|---|
| Fase 1 dan 2: 58 rekaman | [10.5281/zenodo.21467952](https://doi.org/10.5281/zenodo.21467952) | Terbit, CC BY 4.0 |
| Fase 3: 19 sesi kelas, 3 rekaman lokalisasi, dan sesi percobaan | `firmware-riset-lanjutan/capture/` | Belum terbit |

File `.bin` Fase 3 berukuran sekitar 1,5 GB dan ada di `.gitignore`, jadi hanya tersimpan di disk lokal. Label CSV tetap ikut. Rekaman ini memuat MAC board dan BSSID router, jadi perlu ditinjau sebelum diterbitkan.

## Mulai dari mana

| Tujuan | Folder |
|---|---|
| Mengulang rekaman skripsi | [firmware-skripsi-conference](firmware-skripsi-conference/) |
| Melihat hasil skripsi dan paper | [training-skripsi-conference](training-skripsi-conference/) |
| Merekam dengan empat board | [firmware-riset-lanjutan](firmware-riset-lanjutan/) |
| Menjalankan analisis okupansi atau lokalisasi | [analisis-riset-lanjutan](analisis-riset-lanjutan/) |

Kebutuhan bersama semua folder adalah ESP-IDF 5.5.2 untuk firmware dan Python 3 untuk alat rekam serta analisis. Paket Python tiap folder tertulis di README-nya.

## Perbedaan antarfase

Format data kedua sistem berbeda, jadi alat dan mask subcarrier tidak boleh dipertukarkan. Frame juga tidak punya version field, sehingga data yang salah dibaca tetap tampak wajar, bukan error.

| | Fase 1 dan 2 | Fase 3 |
|---|---|---|
| Pemancar | ESP32-C6 kedua | Router |
| Header frame | 28 byte | 50 byte |
| `sig_len` | 47 | 114 |
| Subcarrier nol | 0–5, 127–129, 251–255 | 0–2, 64, 126–130, 192 |
| Identitas board | Tetap di firmware | Dari MAC saat runtime |
| Alat baca | `csi_bin_to_csv.py` | `csi_merge.py` |

Pada Fase 3, subcarrier 252–255 hanya non-nol pada sebagian paket.

## Kredensial

Tidak ada password Wi-Fi di repo ini. Firmware Fase 3 membaca SSID, password, dan alamat kolektor dari `idf.py menuconfig`. Setelah diisi, nilainya tersimpan di `sdkconfig` dan `build/`, jadi kedua lokasi itu tidak boleh dibagikan.

## Lisensi

Repo ini belum punya file lisensi. Firmware dikembangkan dari [esp-csi](https://github.com/espressif/esp-csi) milik Espressif, yang berlisensi Apache-2.0. Dataset Zenodo berlisensi CC BY 4.0.

## Asal kode

Semua folder disusun dari salinan repositori `CSI-PeopleCounting` dan [CSI-ML](https://github.com/Edo-Bagus/CSI-ML). Perubahan terhadap sumbernya dicatat di README tiap folder.
