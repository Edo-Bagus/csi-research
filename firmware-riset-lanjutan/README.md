# Firmware pengambilan data CSI: riset lanjutan

[English version](README.en.md)

Firmware dan alat rekam untuk mengumpulkan Channel State Information (CSI) Wi-Fi dari empat ESP32-C6 dan satu router. Data ini dipakai untuk meneliti okupansi ruang kelas.

Riset ini tidak selesai. Kehadiran orang terdeteksi dari data, tapi jumlah orang dan isi tiap zona belum terjawab. Analisisnya ada di [analisis-riset-lanjutan](../analisis-riset-lanjutan/).

Folder ini untuk sementara memuat semua isi folder riset asli dan belum dipilah. Yang tidak ikut hanya `build/`, serta `ml_people_count/` dan `ml_localization/` yang sudah ada di folder analisis.

## Isi folder

```text
firmware-riset-lanjutan/
├── node/                        Proyek ESP-IDF, satu binary untuk semua board
├── tools/
│   ├── csi_collector.py         Server TCP di laptop, satu file .bin per board
│   ├── csi_merge.py             Menggabungkan .bin ke CSV
│   ├── simulate_node.py         Board tiruan untuk uji tanpa hardware
│   ├── mark_occupancy.py        Mencatat jumlah orang per zona saat rekam
│   ├── label_occupancy.py       Menempelkan label ke CSV
│   ├── mark_events.py           Mencatat penanda waktu saat rekam
│   ├── localize_baseline.py     Aturan argmax untuk lokalisasi
│   └── legacy_uart/             Skrip era UART, tidak dipakai
├── capture/                     Semua rekaman, sekitar 1,5 GB
├── backup/                      Snapshot firmware v1, tidak dipakai
└── docs/                        Catatan asli, runbook, dan dua grafik
```

### Yang berbeda dari sumber

| File | Perubahan |
|---|---|
| `node/main/app_main.c` | 8 baris: 22, 60, 61, 66–68, 70, 74 |
| `node/main/Kconfig.projbuild` | File baru untuk SSID, password, dan alamat kolektor |
| `tools/simulate_node.py` | Baris 33 dan 58 memakai MAC tiruan |
| `backup/v1_tcp_batched_20260909/simulate_node.py` | Sama dengan di atas |
| `backup/v1_tcp_batched_20260909/app_main.c` | Password, SSID, dan identitas laptop disamarkan |
| `docs/` | SSID, alamat laptop, dan MAC disamarkan di 4 dokumen |

File lain disalin tanpa perubahan. `build/` tidak disertakan karena password ikut terkompilasi di dalamnya.

## Cara kerja

```text
ESP #1 ──┐
ESP #2 ──┤
ESP #3 ──┼── Wi-Fi/TCP ──> Router ──> Laptop (csi_collector.py)
ESP #4 ──┘                            Satu file .bin per board
```

1. Tiap board tersambung ke router, lalu melakukan ping ke gateway tiap 100 ms.
2. Board menangkap CSI dari frame router. Pemancarnya router, bukan ESP kedua.
3. Firmware hanya menerima frame dari BSSID router dengan `sig_len` 114.
4. Tiap paket langsung dikirim lewat TCP. Tiap 1 detik board menyisipkan magic `0xDEADBEEF`.
5. `csi_collector.py` menambahkan waktu laptop dan menulis satu file `.bin` per board.
6. `csi_merge.py` menyelaraskan board lewat bin waktu 100 ms.

`node_id` adalah XOR dua byte terakhir MAC, jadi satu binary dipakai untuk semua board. Empat board riset ini punya `node_id` `38`, `4b`, `bf`, dan `d0`.

Tidak ada kabel data saat rekam. USB hanya dipakai untuk flash dan daya.

## Kebutuhan

### Perangkat keras

| Barang | Jumlah | Catatan |
|---|---|---|
| ESP32-C6 | 4 | Semua memakai binary yang sama |
| Router ASUS RT-AX53U | 1 | Pemancar, tanpa WAN |
| Laptop | 1 | Menjalankan kolektor |
| Sumber daya USB | 4 | Power bank atau charger |

### Perangkat lunak

- ESP-IDF 5.5.2
- Python 3
- numpy dan matplotlib, hanya untuk `localize_baseline.py`

Alat rekam lainnya hanya memakai pustaka standar Python. Komponen `esp_csi_gain_ctrl` versinya terkunci di `dependencies.lock`.

## Konfigurasi radio

| Parameter | Nilai |
|---|---|
| Target | ESP32-C6 |
| Kanal, bandwidth | 11 (2,4 GHz), 20 MHz |
| Protokol | IEEE 802.11ax |
| Mode CSI | HE SU, `dcm`, `beamformed`, `he_stbc` 2, 256 subcarrier |
| Pemicu | Ping ke gateway tiap 100 ms, data 32 byte |
| Filter | Sumber sama dengan BSSID, `sig_len` 114 |
| Gain | AGC bebas, nilainya disimpan per paket |
| Power save | Mati |
| Jalur data | TCP port 5566, Nagle mati |

## Build dan flash

Aktifkan environment ESP-IDF terlebih dahulu.

```powershell
$env:PATH = "$env:USERPROFILE\.espressif\tools\idf-python\3.11.2;" + $env:PATH
. C:\esp\v5.5.2\esp-idf\export.ps1
```

Jalankan perintah berikut di folder `node`.

```bash
idf.py set-target esp32c6
```

```bash
idf.py menuconfig
```

Buka menu `CSI riset lanjutan`, lalu isi SSID router, password Wi-Fi, dan alamat IP laptop. Kalau nilainya kosong, build tetap berhasil tapi board tidak akan tersambung.

```bash
idf.py build
```

Ganti `COM5` dengan port board. Binary yang sama di-flash ke keempat board.

```bash
idf.py -p COM5 flash monitor
```

Nilai yang diisi tersimpan di `node/sdkconfig` dan `node/build/`. Keduanya ada di `.gitignore`, dan keduanya tidak boleh dibagikan.

Proyek ini sudah diuji build dari keadaan bersih pada ESP-IDF 5.5.2. Hasil build ini belum diuji ulang di perangkat.

### Memeriksa board

Monitor board yang sehat mencetak:

```text
Node MAC ... -> node_id 0x38
STA connected, BSSID ..., channel 11
Got IP ...
Tersambung ke kolektor ...:5566
node=38 rx=52 sent=52 drop=0 filt=... max_len=512 oversize=0 link=up
```

| Field | Harus | Kalau tidak |
|---|---|---|
| `max_len` | 512 | Bandwidth atau protokol bukan HE20 |
| `link` | `up` | Board tidak menjangkau laptop |
| `drop` | 0 atau kecil | Kolektor tidak menyusul |
| `filt` | Naik pelan | Normal, itu frame `sig_len` lain yang dibuang |

## Menyiapkan jaringan

1. Atur router ke kanal 11, 2,4 GHz, dan 802.11ax aktif.
2. Sambungkan laptop ke jaringan 2,4 GHz router itu.
3. Kunci alamat laptop lewat DHCP reservation di router.
4. Pastikan alamat laptop sama dengan nilai di menuconfig. Kalau berbeda, board harus di-flash ulang.

```bash
ipconfig
```

5. Izinkan port kolektor di Windows Firewall. Jalankan sekali sebagai Administrator.

```powershell
New-NetFirewallRule -DisplayName "CSI Collector 5566" -Direction Inbound -LocalPort 5566 -Protocol TCP -Action Allow
```

Router tidak punya WAN, jadi laptop tidak punya internet selama rekam.

## Menempatkan perangkat

Router berada di tengah ruangan, dan satu board di tiap sudut dengan tinggi seragam. Router tidak boleh bergeser sampai semua sesi selesai, karena sesi sebelum dan sesudahnya tidak lagi sebanding.

Data diambil di dua ruang kelas berbeda. Ruangan 1 berukuran 9 × 7 m, dan ukuran ruangan 2 tidak tercatat.

```text
              9 m
    A ---------------------- B
    |                        |
    |           R            |  7 m
    |       (router)         |
    |                        |
    C ---------------------- D
```

| Zona | Posisi | Ruangan 1 (`count_s*`) | Ruangan 2 (`count_2_*`) |
|---|---|---|---|
| A | Kiri atas | `d0` | `d0` |
| B | Kanan atas | `bf` | `bf` |
| C | Kiri bawah | `38` | `4b` |
| D | Kanan bawah | `4b` | `38` |

Rekaman `loc_*` memakai denah lain: `38` kiri atas, `bf` kanan atas, `d0` kiri bawah, dan `4b` kanan bawah.

Catat denah di catatan sesi setiap mulai di ruangan baru. Frame `.bin` tidak menyimpan denah, dan data tidak bisa menengahi kalau catatannya salah.

Tandai batas zona di lantai dengan lakban. Tiap board mengukur kanal dari router ke board itu, jadi zona adalah sektor arah dari router, bukan kotak yang tegas.

## Langkah perekaman

### Setiap sesi

Satu sesi memakai satu folder. `csi_merge.py` membaca semua `.bin` di folder itu sebagai satu rekaman.

1. Jalankan kolektor lebih dulu, dan tunggu sampai muncul `Kolektor siap`.

```bash
python tools/csi_collector.py --outdir capture/nama_sesi --duration 360 -v
```

2. Nyalakan keempat board bersamaan. Tunggu keempatnya muncul di kolektor.
3. Di terminal kedua, jalankan pencatat label. `--outdir` harus sama dengan kolektor.

```bash
python tools/mark_occupancy.py --outdir capture/nama_sesi
```

Kalau ruangan sudah terisi saat mulai, tambahkan misalnya `--initial A=2,B=1`.

| Tombol | Aksi |
|---|---|
| `a` `b` `c` `d` | Tambah 1 orang di zona itu |
| `A` `B` `C` `D` | Kurangi 1 orang |
| `1` `2` `3` `4` | Set zona A–D ke nol |
| `0` | Kosongkan semua zona |
| `z` | Batalkan tombol terakhir |
| `p` | Cetak keadaan sekarang |
| `q` | Selesai dan tulis file |

4. Hentikan kolektor lebih dulu, lalu tekan `q` di pencatat label. Kalau terbalik, bin terakhir tidak punya label.
5. Periksa hasilnya sebelum lanjut ke sesi berikutnya.

### Di kelas yang sedang berlangsung

Data `count_*` direkam saat kuliah berjalan, jadi subjeknya mahasiswa yang tidak bisa diarahkan. Yang bisa dilakukan tanpa mengatur siapa pun:

- Rekam tanpa putus melintasi bubarnya kelas, dari 10 menit sebelum kelas berakhir sampai 10 menit setelah ruangan kosong.
- Rekam ruangan kosong di jam dan hari berbeda, masing-masing 5 menit.
- Rekam kelas dengan ukuran berbeda.

### Lokalisasi

Ada tiga rekaman di folder terpisah.

| Folder | Isi | Durasi |
|---|---|---|
| `capture/loc_baseline` | Ruangan kosong | 2 menit |
| `capture/loc_static` | Berdiri 30 detik di tiap sudut lintasan | 2,5 menit |
| `capture/loc_walk` | Berjalan memutar 8 lap | 5,5 menit |

Urutan jalan adalah `4b`, `bf`, `38`, `d0`, dengan radius 2–2,5 m dari router. Untuk `loc_walk`, jalankan pencatat penanda dan tekan Enter tiap melewati sudut.

```bash
python tools/mark_events.py --outdir capture/loc_walk
```

Prosedur lengkapnya ada di `docs/LOCALIZATION_RUNBOOK.md`.

## Memeriksa hasil rekaman

```bash
python tools/csi_merge.py capture/nama_sesi --stats-only --bin-ms 100
```

| Yang dilihat | Nilai yang diharapkan |
|---|---|
| Node | 4 |
| Laju per board | Sekitar 35–45 paket per detik |
| Bin berisi semua node | Di atas 90% |
| `hilang` | Kecil |

Untuk membuat CSV berlabel:

```bash
python tools/csi_merge.py capture/nama_sesi -o nama_sesi.csv --bin-ms 100
```

```bash
python tools/label_occupancy.py nama_sesi.csv --occupancy capture/nama_sesi/occupancy.csv -o nama_sesi_labeled.csv
```

### Kalau ada masalah

| Gejala | Kemungkinan penyebab | Yang dicek |
|---|---|---|
| `connect() ... gagal` berulang | Alamat laptop berbeda, atau kolektor belum jalan | `ipconfig`, terminal kolektor |
| `link=down` tapi `rx` naik | CSI masuk, TCP tidak tersambung | Firewall dan alamat laptop |
| `rx=0` terus | Tidak ada CSI | Router harus di kanal 11 dengan 802.11ax aktif |
| `max_len` bukan 512 | Bandwidth bukan HE20 | Pengaturan router |
| Board tidak tersambung Wi-Fi | SSID atau password salah, atau jaringan 5 GHz | Nilai di menuconfig |
| Laju sekitar 10 paket per detik | Board tidak hidup bersamaan | Nyalakan keempatnya serentak |
| Bin berisi semua node 0% | Waktu nyala board tidak beririsan | Ulangi sesi |

## Uji tanpa hardware

Jalankan kolektor di satu terminal.

```bash
python tools/csi_collector.py --host 127.0.0.1 --outdir uji_simulasi --duration 15
```

Jalankan board tiruan di terminal lain.

```bash
python tools/simulate_node.py --nodes 4 --rate 40 --duration 10
```

Lalu periksa dengan `csi_merge.py`. Opsi `--drop-rate`, `--split-writes`, dan `--garbage` menguji ketahanan kolektor. Jalur ini sudah diuji: 960 paket terkirim dan 960 tersimpan tanpa gap.

## Format file `.bin`

File berisi rangkaian record, little-endian dan packed. Magic `0xDEADBEEF` dari board tidak ikut tersimpan.

| Bagian | Tipe | Keterangan |
|---|---|---|
| `host_time` | `float64` | Waktu laptop saat frame selesai dibaca |
| `payload_len` | `uint32` | Panjang frame |
| Frame | `payload_len` byte | Header 50 byte, lalu data CSI |

Header frame:

| Offset | Tipe | Field | Keterangan |
|---|---|---|---|
| 0 | `uint32` | `seq` | Penghitung lokal board |
| 4 | `uint8` | `node_id` | XOR dua byte terakhir MAC |
| 5 | `uint8[6]` | `node_mac` | MAC board |
| 11 | `int16` | `rssi` | RSSI (dBm) |
| 13 | `uint8` | `rate` | Nilai rate dari driver |
| 14 | `int8` | `noise_floor` | Noise floor |
| 15 | `int8` | `fft_gain` | Gain FFT |
| 16 | `uint8` | `agc_gain` | Gain AGC |
| 17 | `uint8` | `channel` | Kanal Wi-Fi |
| 18 | `uint8` | `first_word_invalid` | Penanda dari driver |
| 19 | `uint8[6]` | `ap_mac` | BSSID router |
| 25 | `uint32` | `timestamp` | Timestamp penerima (µs), jam lokal board |
| 29 | `uint64` | `uptime_us` | Jam board saat capture |
| 37 | `uint64` | `sent_us` | Jam board saat masuk socket |
| 45 | `uint16` | `sig_len` | Panjang paket, selalu 114 |
| 47 | `uint8` | `rx_state` | Status penerimaan |
| 48 | `uint16` | `len` | Jumlah nilai CSI, selalu 512 |
| 50 | `int16[len]` | `csi` | Data CSI |

Format struct Python untuk header:

```python
HEADER = struct.Struct("<I B 6s h B b b B B B 6s I Q Q H B H")
```

Frame tidak punya version field. Kalau struct di firmware berubah, `csi_collector.py`, `csi_merge.py`, dan `simulate_node.py` harus ikut berubah. Ketidakcocokan menghasilkan data yang terbaca tapi salah, bukan error.

## Hal yang perlu diketahui

- **Laju paket mengikuti jumlah board.** Tiap board hanya melakukan ping 10 kali per detik, tapi lajunya sekitar 10 × jumlah board yang hidup.

| Keadaan | Board hidup | Laju per board |
|---|---|---|
| `sesi4` dan 4 file tambahan di `count_s09`, board menyala bergantian | 1 | 9,9–10,2 Hz |
| `sesi2` | 2 | 20,9–21,5 Hz |
| `count_s01` setelah `bf` mati di detik 11 | 3 | 26,5–35,5 Hz |
| `sesi3`, `count_s05`, `count_2_4` | 4 | 36,0–43,5 Hz |

- **Board menangkap frame fisik yang sama.** Pada 5 sesi, 84–99,9% paket punya pasangan di board lain dalam ±100 µs menurut `timestamp`. Kontrol dengan offset digeser 7,3 ms hanya mendapat 0,4–1,3%. Alamat tujuan frame tidak tersimpan, jadi dugaan bahwa frame itu balasan ping untuk board lain belum terbukti. Firmware tidak menyimpan `dmac` dan `rx_seq` yang bisa memastikannya.
- **Patokan paket hilang adalah `hilang` dari `csi_merge.py`.** `gap` di kolektor tidak menghitung paket yang hilang saat resync.
- **Subcarrier aktif.** Indeks 0–2, 64, 126–130, dan 192 selalu nol. Sebanyak 242 indeks lain non-nol pada hampir semua paket, dan indeks 252–255 hanya non-nol pada 16–58% paket. Letak ini berbeda dari data skripsi, jadi mask skripsi tidak boleh dipakai.
- **Nilai CSI mentah.** Firmware tidak mengompensasi gain, dan AGC berjalan bebas.
- **Tidak semua isi `capture/` sesi utama.** Sesi utama adalah `count_s01`–`count_s10`, `count_2_1`–`count_2_9`, dan `loc_*`. Sisanya tampak percobaan. Dua file di `sesi1` memakai header lama 42 byte, jadi tidak terbaca oleh alat di sini. `count_s09` punya 4 file kecil tambahan, dan `count_s01_kosong` hanya berisi label.
- **Rekaman memuat identitas perangkat.** Nama file dan isi frame memuat MAC board dan BSSID router. Perhatikan ini kalau data diterbitkan.
- **`capture/` di sini bukan cadangan.** Folder ini berada di disk yang sama dengan sumbernya.

### Komentar yang sudah usang

Komentar dan catatan berikut sengaja tidak diubah.

| Lokasi | Tertulis | Kenyataan |
|---|---|---|
| `node/main/app_main.c` baris 77 | Sekitar 10 paket per detik | Sekitar 40 pada 4 board |
| `node/main/app_main.c` baris 118 | Sekitar 13 paket per detik | Sekitar 40 pada 4 board |
| `node/main/app_main.c` baris 315–317 | Dua board mengamati paket berbeda | Board menangkap frame yang sama |
| `tools/csi_merge.py` baris 8–11 | Paket tiap board berbeda | Board menangkap frame yang sama |
| `tools/mark_occupancy.py` | Layar menampilkan A = `38`, C = `d0` | Tidak cocok dengan ruangan 1 maupun 2. Label tidak terpengaruh |
| `node/sdkconfig.defaults` | Mode log teks RSSI dan `printf` dari callback | Firmware sekarang stream TCP |
| `docs/KNOWLEDGE.md` §0.3 | Header 42 byte | Header 50 byte |
| `docs/KNOWLEDGE.md` §2.2, §2.4, §3, §4, §6, §8, §10 | Mode log RSSI, ping 1000 ms | Warisan sebelum v2 |
| `docs/KNOWLEDGE.md` §0.4 | Paket tiap board berbeda | Board menangkap frame yang sama |
| `docs/COUNTING_RUNBOOK.md` | Router membalas lebih dari sekali per ping | Board sendirian mendapat 10 Hz |
| `docs/COUNTING_RUNBOOK.md` baris 42 | Denah di `ml_people_count/loader.py` | Sekarang di `src/csi_occupancy/datasets.py` |

## Dataset

Rekaman Fase 3 belum diterbitkan.

## Asal kode

Firmware ini dikembangkan dari `CSI_recv_v2`, yang berasal dari contoh `get-started` pada [esp-csi](https://github.com/espressif/esp-csi) milik Espressif, yang berlisensi Apache-2.0. Salinan ini diambil dari `esp/RISET_CSI_2/` di `CSI-PeopleCounting`.
