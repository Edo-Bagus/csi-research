# KNOWLEDGE.md — Serah-terima konteks RISET_CSI_2

> Dokumen ini ditujukan untuk **agent/developer berikutnya** yang membuka folder ini
> tanpa riwayat percakapan sebelumnya. Tujuannya: memberi konteks yang **tidak bisa
> disimpulkan dari membaca kode saja**. Baca ini lebih dulu sebelum mengubah apa pun.
>
> Terakhir diperbarui: 2026-09-19 (+ Bagian 13: dataset kedua `data-15-9` di
> RUANGAN LAIN, refactor `loader.Dataset`, dan temuan KOHERENSI TEMPORAL yang
> kini menjadi hasil utama. Bagian 12 tetap berlaku untuk ruangan 1, KECUALI
> §12.4 dan §12.7 yang direvisi oleh §13.4-13.6.)

---

## 0. STATUS — v2, TERVERIFIKASI DI HARDWARE (baca ini dulu)

Folder ini **tidak lagi** firmware log-RSSI single-node lewat UART. Sekarang:

**Sistem pengumpulan CSI multi-STA lewat Wi-Fi.** N board ESP32-C6 masing-masing
berasosiasi ke router, memanen CSI, dan mengirimnya lewat **TCP ke laptop kolektor**
yang berada di router yang sama. **Tidak ada kabel USB sama sekali** saat capture.

```
   ESP #1 ──┐
            ├── Wi-Fi/TCP ──> Router <SSID> ──> Laptop (csi_collector.py)
   ESP #2 ──┘                                        1 file .bin per node
```

Akibatnya beberapa bagian dokumen lama di bawah **sudah tidak berlaku**:

| Bagian lama | Status sekarang |
|---|---|
| §2.2 mode LOG RSSI | **Tidak berlaku.** Mode aktif = stream CSI biner via TCP. Varian RSSI disimpan di `main/app_main_rssi_log.c.bak`. |
| §2.3 `tools/*.py` tidak berpasangan | **Sudah diperbaiki.** `csi_collector.py` + `csi_merge.py` cocok dengan firmware ini. Skrip UART lama (`csi_uart_capture.py`, `csi_bin_to_csv.py`) kini yang usang. |
| §2.4 `PING_INTERVAL_MS` 1000 ms | **Kembali ke 100 ms** (~10 pkt/s), karena tidak ada lagi `printf` di jalur data. |
| §4 cara kembali ke dump CSI | Tidak relevan; CSI sekarang selalu dikirim, bukan dicetak. |
| §5 jalur biner UART | Digantikan jalur TCP. Format frame berubah, lihat §0.3. |
| §8.5 belum pernah di-build | **Selesai.** Build terverifikasi 2026-09-09. |

### 0.1. Identitas node dari MAC — satu binary untuk semua board

`CONFIG_TX_ID` compile-time **dihapus**. `node_id` sekarang diturunkan runtime dari
MAC factory (`node_id_from_mac()` = XOR dua byte terakhir), dan MAC lengkap ikut
dikirim di tiap frame. Jadi **flash binary yang sama ke semua board** — tidak ada
lagi risiko dataset salah label karena salah build.

### 0.2. `msg_id` dihapus, diganti `seq`

Field lama `msg_id` diisi dari `payload + 15` — peninggalan era ESP-NOW yang tidak
valid untuk ICMP reply. Terbukti konstan `1157629952` di seluruh 302 baris
`../CSI_recv_v2/test_ap.csv`. Penggantinya `seq`: counter lokal per node, monotonic,
dipakai kolektor untuk menghitung paket hilang.

### 0.3. Format frame (header **50 B** v2, packed, little-endian)

```c
uint32 seq | uint8 node_id | uint8 node_mac[6] | int16 rssi | uint8 rate
int8 noise_floor | int8 fft_gain | uint8 agc_gain | uint8 channel
uint8 first_word_invalid | uint8 ap_mac[6] | uint32 timestamp
uint64 uptime_us | uint64 sent_us | uint16 sig_len | uint8 rx_state | uint16 len
```

`uptime_us` = jam board saat paket ditangkap radio. `sent_us` = jam board saat frame
masuk socket. Selisihnya = lama antre di dalam board, yang memisahkan backpressure
board dari jitter jaringan.

diikuti `len` × `int16` data CSI. Magic `0xDEADBEEF` disisipkan tiap 1 detik di batas
frame untuk resync.

> **Tidak ada version field.** Kalau struct diubah, `csi_collector.py` **dan**
> `csi_merge.py` harus diubah di commit yang sama. Ketidakcocokan menghasilkan data
> yang terparsing tapi isinya sampah — bukan error. Ukuran header 42 B sudah
> diverifikasi cocok antara C (`offsetof`) dan Python (`struct.calcsize`).

### 0.4. Alignment antar-node = skema (a) time-binned

Tiap board nge-ping router **sendiri-sendiri**, jadi paket yang diamati board A dan
board B **bukan paket yang sama**. Yang bisa disejajarkan hanya jendela waktunya.

**Sumber waktu (v2).** `csi_merge.py` TIDAK lagi memakai `host_time` mentah. Ia
merekonstruksi waktu capture: jarak antar-paket diambil dari `uptime_us` (jam board,
presisi, bebas jitter jaringan), lalu seluruh sumbu waktu tiap node digeser ke jam
laptop dengan SATU offset (persentil-10 dari `host_time - uptime`, karena paket
tercepat paling sedikit tertunda). Pakai `--use-host-time` untuk membandingkan.

**Coverage terukur di hardware nyata, 2026-09-09:**

| bin | 2 board | **4 board** |
|---|---|---|
| 30 ms | — | 77.0% |
| 50 ms | 84.1% | 84.4% |
| 75 ms | 89.3% | 93.0% |
| **100 ms** | 92.9% | **97.2%** |
| 150 ms | 95.2% | 97.4% |
| 200 ms | 95.7% | 97.9% |

**Pakai `--bin-ms 100`.** Dengan 4 board, coverage-nya praktis sama dengan 150 ms tapi
resolusi waktunya dua kali lebih halus.

Efek rekonstruksi waktu: 4 board @150 ms = **97.4%** (rekonstruksi) vs **92.7%**
(`host_time` mentah).

> **Temuan yang berlawanan dengan dugaan:** menambah node membuat penyelarasan makin
> MUDAH, bukan makin sulit. Model independen memperkirakan ~0,95^4 ≈ 89% untuk empat
> node; hasil nyatanya 97,4%. Sebabnya board tidak benar-benar independen — masing-
> masing nge-ping tiap 100 ms dan router melayani bergiliran, jadi paketnya
> terdistribusi lebih rata daripada acak.

### 0.5. File baru

| File | Peran |
|---|---|
| `main/app_main.c` | Firmware TCP streaming (menggantikan versi RSSI). |
| `main/app_main_rssi_log.c.bak` | Varian log RSSI lama. Tidak ikut dikompilasi (bukan `.c`). |
| `tools/csi_collector.py` | **Server TCP di laptop.** 1 file `.bin` per node, membubuhkan `host_time`. |
| `tools/csi_merge.py` | `.bin` multi-node → CSV, dengan kolom `bin` untuk penyelarasan. |
| `tools/simulate_node.py` | Client ESP palsu untuk uji tanpa hardware (punya fault model). |
| `RUNBOOK.md` | **Prosedur capture saat OFFLINE.** Semua perintah siap salin. |
| `backup/v1_tcp_batched_20260909/` | Snapshot v1 lengkap + data capture aslinya. |
| `capture/sesi2/`, `capture/sesi3/` | Hasil capture v2 (2 board dan 4 board). |

### 0.6. Status: BEKERJA, terverifikasi 4 board

Capture nyata 2026-09-09, 4 board, 29 detik, `capture/sesi3/`:

```
Node          : 4
  <MAC>: 1113 paket, 39.7 pkt/s, hilang=0, rssi -54..-43
  <MAC>: 1022 paket, 36.3 pkt/s, hilang=0, rssi -42..-37
  <MAC>: 1120 paket, 38.9 pkt/s, hilang=0, rssi -38..-30
  <MAC>: 1134 paket, 39.5 pkt/s, hilang=0, rssi -47..-33
Bin 150 ms   : 193 terisi, 188 berisi semua 4 node (97.4%)
```

- **`hilang=0` di keempat node.** Nol paket hilang, nol duplikat.
- 100% `sig_len=114`, `len=512` (256 subcarrier) di semua paket.
- RSSI terpisah rapi: -32 / -36 / -40 / -46 dBm — empat sudut pandang berbeda.
- Jitter jaringan p50 10-19 ms; antrean dalam board p99 1,6-34 ms.

**Skalabilitas.** Tidak ada yang meng-hardcode jumlah node: firmware memakai MAC
sendiri, kolektor satu thread per koneksi (`listen(8)`), `csi_merge.py` memakai
`n_nodes = len(per_node)`. Menambah board = flash binary yang sama, tanpa build ulang.
Untuk >8 board, naikkan backlog `listen()`.

**Yang belum dikerjakan:**

1. Kumpulkan dataset berlabel sungguhan (dengan orang di ruangan).
2. Sambungkan hasil capture ke pipeline ML di `ml/dataset_*/`.
3. **Self-interference belum terukur.** Board mengirim CSI lewat radio yang sama
   dengan yang sedang diukur. Efeknya kemungkinan kecil (~20 KB/s per board) tapi
   belum dibuktikan. Kalau butuh bukti untuk skripsi, satu board masih bisa dipakai
   membandingkan capture USB vs TCP.
4. `rx_state != 0` muncul di 0-0,4% paket. Terlalu kecil untuk dipedulikan sekarang;
   bisa difilter di `csi_merge.py` kalau nanti terbukti mengganggu.

---

## 1. Apa ini, dalam satu paragraf

Firmware **penerima (receiver) CSI** untuk skripsi *people counting* berbasis Wi-Fi
Channel State Information. Berjalan di **ESP32-C6** dengan **ESP-IDF 5.5.2**. Board
berasosiasi sebagai station ke sebuah router, mem-ping gateway untuk membangkitkan
trafik, lalu memanen CSI dari paket balasan. Folder ini adalah **hasil clone bersih**
dari `../CSI_recv_v2` — hanya berisi yang dibutuhkan untuk membangun firmware.

---

## 2. Fakta yang paling sering disalahpahami

Empat hal ini adalah sumber kebingungan terbesar. Pahami dulu sebelum menyentuh kode.

### 2.1. Pemancarnya adalah ROUTER, bukan ESP kedua

Di repo induk ada `CSI_send`, `CSI_send_v2`, dan `Monitor`. **Tidak satu pun dipakai
oleh firmware ini.** Semua sender itu adalah broadcaster **ESP-NOW**, sedangkan
`app_main.c` di sini sudah sepenuhnya meninggalkan ESP-NOW (nol kemunculan `esp_now`
di kode). Sumber trafik sekarang:

```
Router <SSID>  ──(asosiasi STA + balasan ICMP ping)──>  ESP32-C6 (folder ini)
```

Kalau CSI tidak keluar, **periksa router dulu**, bukan mencari board pemancar.

### 2.2. Mode aktif saat ini = LOG RSSI, bukan capture dataset

`wifi_csi_rx_cb()` sekarang hanya mencetak satu baris pendek per paket:

```
#153 rssi=-42 nf=-97
```

Akuisisi CSI **tetap menyala** (`wifi_csi_init()` tidak diubah) — yang dimatikan hanya
pencetakannya. Blok metadata lengkap dan dump (I,Q) per subcarrier **masih ada di file,
dalam bentuk komentar**, sengaja tidak dihapus. Lihat §4 untuk cara menghidupkannya.

### 2.3. `tools/*.py` TIDAK berpasangan dengan `main/app_main.c` di folder ini

Ini jebakan paling mahal. Ketiga skrip Python di `tools/` mem-parsing **frame biner**
`0xDEADBEEF`. Firmware di folder ini **tidak pernah** menghasilkan frame itu — ia
mencetak teks biasa. Menjalankan `csi_uart_capture.py` terhadap firmware ini akan
menghasilkan file yang tidak pernah tersinkronisasi (menunggu magic yang tak kunjung
datang).

Firmware yang menghasilkan frame biner ada di:

```
../CSI_recv_v2/main/app_main copy.txt
```

File itu **sengaja tidak ikut di-clone** (keputusan eksplisit pemilik repo: folder ini
ingin dijaga bersih). Kalau butuh mode capture, lihat §5.

### 2.4. `PING_INTERVAL_MS` sekarang 1000 ms, dan itu disengaja

Nilai aslinya 100 ms (10 paket/detik) untuk pengumpulan dataset. Diperlambat jadi
1000 ms supaya log terbaca manusia. **Jangan menaikkan rate ini sambil membiarkan
dump CSI aktif** — alasannya di §4.

---

## 3. Peta file

> **Catatan v2:** tabel di bawah ini warisan dokumen lama. Skrip `legacy_uart/*`
> sudah TIDAK dipakai (header 28 B, jalur UART). Tools aktif ada di §0.5.

| File | Peran |
|---|---|
| `main/app_main.c` | Satu-satunya sumber firmware. 7 fungsi, ~405 baris. |
| `main/CMakeLists.txt` | `REQUIRES` sudah dipangkas dari versi lama (lihat §7). |
| `main/idf_component.yml` | Dependensi: `esp_csi_gain_ctrl` saja. |
| `sdkconfig.defaults` | Konfigurasi minimal. **Ini file ter-track**, `sdkconfig` tidak. |
| `tools/legacy_uart/csi_uart_capture.py` | Serial → `.bin`. Sinkronisasi ke magic `0xDEADBEEF`. |
| `tools/legacy_uart/csi_bin_to_csv.py` | `.bin` → `.csv`. Struct `<I B h B b b B B B 6s I H B H`. |
| `tools/legacy_uart/simulate_capture.py` | Generator dummy + fault model, untuk uji parser tanpa hardware. |

Struktur `app_main.c` (nomor baris per 2026-09-09, akan bergeser kalau diedit):

| Baris | Fungsi | Catatan |
|---|---|---|
| 95 | `reconnect_timer_cb` | One-shot timer, delay 2 s. |
| 101 | `wifi_event_handler` | STA_CONNECTED / DISCONNECTED / GOT_IP. |
| 146 | `wifi_init` | Band/protocol/bandwidth/channel + config STA. |
| 194 | `icmp_ping_task` | Traffic generator, ping gateway. |
| 251 | `wifi_csi_rx_cb` | **Callback CSI — di sinilah semua aksi terjadi.** |
| 349 | `wifi_csi_init` | Konfigurasi akuisisi CSI (HE-SU). |
| 372 | `app_main` | Orkestrasi. |

---

## 4. Cara mengembalikan mode dump CSI

Semua di `main/app_main.c`, dalam `wifi_csi_rx_cb()`:

1. **Komentari** baris RSSI aktif (sekitar baris 311–312):
   ```c
   printf("#%" PRIu32 " rssi=%d nf=%d\n",
          s_recv_count, rx_ctrl->rssi, rx_ctrl->noise_floor);
   ```
2. **Uncomment** blok metadata lengkap — ditandai `// [DIKOMENTARI] Baris metadata lengkap`.
3. **Uncomment** blok dump (I,Q) — ditandai `// [DIKOMENTARI] Dump nilai mentah`.
4. Perbarui komentar header file (baris 1–19) supaya tidak menyesatkan.

**Peringatan kinerja — jangan dilewati.** Dump CSI penuh adalah ~2,5 KB `printf`
yang dieksekusi **dari dalam konteks callback driver Wi-Fi**. Pada 1 paket/detik ini
sepele. Pada 10 paket/detik (`PING_INTERVAL_MS 100`) ia akan memblokir driver dan
menyebabkan paket ter-drop diam-diam. Jadi:

- Mode dump CSI ke **log** → pertahankan `PING_INTERVAL_MS 1000`.
- Mode **capture dataset** rate tinggi → jangan pakai `printf`; pakai jalur biner (§5),
  yang memindahkan I/O ke task terpisah lewat message buffer.

Pertimbangan desain: kalau mode ini akan sering ditukar, lebih baik ubah jadi saklar
`#define CSI_LOG_MODE_RSSI 1` dengan `#if/#else/#endif` daripada uncomment 20 baris
tiap kali. Kode lama tetap ikut ter-syntax-check editor. Ini **belum** diterapkan.

---

## 5. Cara kembali ke mode capture dataset (jalur biner)

Firmware di folder ini tidak punya jalur biner. Langkahnya:

1. Ambil `../CSI_recv_v2/main/app_main copy.txt` — itu versi lengkap STA+ping dengan
   UART biner (687 baris, `PING_INTERVAL_MS 100`).
2. Salin jadi `main/app_main.c` di folder ini (ganti yang ada), atau simpan sebagai
   varian terpisah.
3. Naikkan baud di `sdkconfig.defaults` → `CONFIG_ESP_CONSOLE_UART_BAUDRATE=921600`,
   lalu hapus `sdkconfig` dan build ulang.
4. Capture: `python tools/legacy_uart/csi_uart_capture.py COM15 -b 921600 -o data.bin`
5. Konversi: `python tools/legacy_uart/csi_bin_to_csv.py data.bin --expand-csi`

### Format frame biner (referensi)

```
MAGIC 0xDEADBEEF (4 B, LE: ef be ad de)
  └─ N × [ header 28 B packed  +  len × int16 ]
```

Header, harus cocok dengan `HEADER_STRUCT` di `csi_bin_to_csv.py`:

```c
uint32 msg_id | uint8 tx_id | int16 rssi | uint8 rate | int8 noise_floor
int8 fft_gain | uint8 agc_gain | uint8 channel | uint8 first_word_invalid
uint8 mac[6]  | uint32 timestamp | uint16 sig_len | uint8 rx_state | uint16 len
```

> Kalau struct di firmware diubah, **`csi_bin_to_csv.py` dan `simulate_capture.py`
> harus diubah serentak** — tidak ada mekanisme versi di frame, jadi ketidakcocokan
> akan menghasilkan CSV yang terparsing tapi isinya sampah.

Bukti jalur ini pernah berfungsi: `../CSI_recv_v2/test_ap.csv` (302 baris, `len=512`,
MAC `<MAC>`).

---

## 6. Parameter radio dan artinya

Semua `#define` di `main/app_main.c` baris 46–72.

| Parameter | Nilai | Kenapa |
|---|---|---|
| `CONFIG_LESS_INTERFERENCE_CHANNEL` | 11 | Channel paling sepi di lokasi pengujian. |
| `CONFIG_WIFI_2G_BANDWIDTHS` | `WIFI_BW_HT20` | 20 MHz → **256 subcarrier** pada 802.11ax. |
| `CONFIG_WIFI_2G_PROTOCOL` | `WIFI_PROTOCOL_11AX` | HE. Menentukan jumlah subcarrier. |
| `CONFIG_CSI_MAX_LEN` | 1024 | Batas buffer dalam int16 (= 512 subcarrier kompleks). |
| `CONFIG_FORCE_GAIN` | 0 | Baseline gain **direkam** dari 100 paket pertama tapi **tidak** dipaksakan. |
| `PING_INTERVAL_MS` | 1000 | Lihat §2.4. |

Nilai normal yang teramati: `info->len = 512` → 256 subcarrier. Kalau `len` berbeda,
kemungkinan besar protokol/bandwidth tidak sesuai harapan.

**Soal `CONFIG_FORCE_GAIN`:** saat 0, AGC bebas bergerak, sehingga amplitudo CSI ikut
terpengaruh perubahan gain — bukan murni perubahan kanal. Untuk dataset yang
dibandingkan antar sesi, mengaktifkannya (nilai 1) membuat amplitudo lebih konsisten.
Ini **belum pernah diuji** pada setup ini; catat sebagai kandidat eksperimen.

Konfigurasi akuisisi CSI di `wifi_csi_init()` spesifik HE-SU: `acquire_csi_su=true`,
sedangkan `legacy`/`ht20`/`ht40`/`mu` semuanya `false`. Jadi **hanya paket HE SU yang
menghasilkan CSI** — konsisten dengan router 802.11ax. Kalau router jatuh ke mode
legacy/HT, callback akan sunyi meski koneksi Wi-Fi sehat.

---

## 7. Perubahan yang dilakukan saat clone (beda dari `CSI_recv_v2`)

| Berkas | Perubahan | Alasan |
|---|---|---|
| `main/CMakeLists.txt` | `fatfs sdmmc led_strip` dibuang; `esp_event lwip` ditambah | Sisa varian SD-card; kode aktif tidak memakainya. `lwip` dibutuhkan `ping_sock.h`. |
| `main/idf_component.yml` | `espressif/led_strip` dihapus | Tidak ada kode LED. |
| `sdkconfig.defaults` | **File baru** | `CSI_recv_v2` hanya punya `sdkconfig` yang ter-*gitignore* — konfigurasinya tidak terekam di mana pun. |
| `.gitignore` | + `!sdkconfig.defaults`, + ignore artefak analisis | Agar konfigurasi ikut ter-track. |
| `.vscode/settings.json` | `compile-commands-dir` → `RISET_CSI_2\build` | Kalau tidak, clangd mengindeks folder lama. |

`main/app_main.c` **disalin apa adanya, tanpa satu pun perubahan.**

Tidak ikut di-clone: `build/`, `managed_components/`, `sdkconfig`, ketiga file backup
(`backup.txt`, `backup-lagi.txt`, `app_main copy.txt`), dan seluruh artefak data
(`*.bin`, `*.csv`, `*.npy`, `_*.html/json/js`). Semua masih aman di `../CSI_recv_v2`.

---

## 8. Utang teknis dan risiko yang diketahui

Diurutkan dari yang paling perlu diperhatikan.

1. **Kredensial Wi-Fi hardcoded.** `WIFI_STA_SSID` dan `WIFI_STA_PASSWORD` ada sebagai
   literal di `app_main.c` baris 53–54. `.gitignore` **tidak** melindungi ini — begitu
   folder di-commit, SSID dan password masuk riwayat git permanen. Dibiarkan apa adanya
   karena di luar lingkup permintaan; angkat ke `Kconfig`/`menuconfig` kalau repo akan
   dipublikasikan.
2. **Folder induk belum pernah di-commit.** `CSI_recv_v2` berstatus untracked di git.
   Folder ini juga baru dibuat dan belum di-commit (keputusan eksplisit pemilik repo:
   commit adalah keputusannya, bukan agent).
3. **`CSI_PRINT_VALUES` kini hanya dirujuk dari komentar.** Tidak memicu warning karena
   berbentuk `#define`, tapi akan jadi *dead define* kalau mode CSI tidak pernah
   dihidupkan lagi.
4. **`printf` dari konteks callback driver Wi-Fi.** Aman di 1 pkt/s, rapuh di atas itu.
   Lihat §4.
5. **Belum pernah di-build di folder ini.** Perubahan `CMakeLists.txt`/`idf_component.yml`
   masuk akal secara statis tapi **belum diverifikasi kompilasi**. Build pertama adalah
   langkah wajib berikutnya.

---

## 9. Membaca output RSSI

```
#153 rssi=-42 nf=-97
```

- `rssi` — kuat sinyal terima, dBm.
- `nf` — *noise floor*, dBm. Lantai kebisingan radio; makin negatif makin sunyi.
- **SNR = rssi − nf.** Contoh di atas: −42 − (−97) = **55 dB** (sangat baik).

| SNR | Kualitas |
|---|---|
| > 40 dB | Sangat baik |
| 25–40 dB | Baik |
| 15–25 dB | Cukup |
| < 10 dB | Buruk |

**Penting untuk konteks skripsi:** link yang *terlalu* kuat belum tentu ideal untuk
people counting. RSSI −42 dBm menandakan komponen line-of-sight dominan, yang bisa
menenggelamkan komponen multipath — padahal justru pantulan itulah yang berubah saat
orang bergerak. Gunakan log RSSI ini untuk **validasi kesehatan link dan penempatan
perangkat**, bukan sebagai fitur utama counting. Fitur utama tetap CSI (256 subcarrier),
karena perubahan yang tak terlihat di RSSI agregat sering jelas di subcarrier tertentu.

Yang layak dipantau saat pengukuran: kestabilan `nf` (lonjakan = interferensi datang-
pergi, mencemari dataset), kestabilan `rssi` saat ruangan kosong, dan besar delta saat
ada orang di antara TX–RX.

---

## 10. Perintah yang sering dipakai

```bash
# Build pertama (folder ini belum pernah di-build)
idf.py set-target esp32c6
idf.py build

# Flash + monitor (port dari .vscode/settings.json: COM15)
idf.py -p COM15 flash monitor

# Reset konfigurasi ke sdkconfig.defaults
rm sdkconfig && idf.py build

# Uji parser tanpa hardware
python tools/legacy_uart/simulate_capture.py --seed 42 | head
```

Environment: ESP-IDF terpasang di `C:\esp\v5.5.2\esp-idf` (lihat `.vscode/settings.json`).

---

## 11. Kalau kamu agent yang baru membuka folder ini

Urutan yang disarankan:

1. Baca §2 sampai paham keempat poinnya — di situ letak semua jebakannya.
2. Jalankan `idf.py build` untuk memverifikasi §8 poin 5 sebelum mengubah apa pun.
3. Jangan menghapus blok komentar CSI di `wifi_csi_rx_cb()`; itu bukan sampah,
   melainkan mode kedua yang sengaja disimpan.
4. Kalau diminta "kembalikan ke CSI", tanyakan dulu maksudnya: **dump ke log** (§4)
   atau **capture dataset biner** (§5). Keduanya berbeda jauh.
5. Kalau tugasnya soal DATA/ML (bukan firmware), baca §12 — terutama §12.1:
   data diambil di kelas yang sedang berlangsung, jadi protokol yang
   mengandaikan kendali atas orang tidak berlaku.
6. Perbarui dokumen ini kalau kamu mengubah hal yang tidak terbaca dari kode.

---

## 12. Dataset counting `data-14-9` dan konteks pengambilannya

> Ditambahkan 2026-09-14. Bagian ini tentang **data dan analisisnya**, bukan
> firmware. Analisis lengkap ada di `ml_people_count/eda_people_count.ipynb`.

### 12.1. Data ini diambil di KELAS YANG SEDANG BERLANGSUNG

**Ini fakta terpenting di bagian ini, dan tidak bisa disimpulkan dari file mana
pun.** Sepuluh sesi `count_s01`–`count_s10` direkam 2026-09-14 pukul 12:50–15:19
secara berurutan, di ruang kelas yang sedang dipakai kuliah. Subjeknya mahasiswa
yang sedang kuliah, **bukan relawan yang bisa disuruh berdiri di posisi
tertentu**.

Akibatnya, sejumlah hal yang tampak seperti cacat pengumpulan data sebenarnya
adalah rekaman yang benar dari apa yang terjadi:

| Yang terlihat di data | Sebabnya |
|---|---|
| Okupansi konstan 5 menit per sesi | Mahasiswa duduk dan tetap duduk. Itu memang bentuk kelas. |
| Tidak ada kelas 1–6 orang | Kelas tidak pernah terisi separuh lalu penuh lagi. Yang ada: kosong atau penuh. |
| Zona B hampir selalu kosong | Sudut ruangan itu memang tidak dipakai duduk. |
| Rentetan tombol di awal tiap sesi | Keadaan awal ruangan diketikkan karena kelas SUDAH duduk saat perekaman mulai. Ini tindakan yang benar. |

**Jangan merekomendasikan protokol pengambilan data yang mengandaikan kendali
atas orang** — "tahan 60 detik di tiap tingkat", "kosongkan zona lain", "satu
orang berjalan sendiri". Semua itu tidak tersedia di sini. Rekomendasi apa pun
harus berupa sesuatu yang bisa dilakukan tanpa mengatur siapa pun.

### 12.2. Framing riset yang tepat

Ini **bukan** eksperimen counting terkontrol yang gagal. Ini **penginderaan
oportunistik di lingkungan tak terkendali** — setting yang lebih sulit dan lebih
layak publikasi daripada studi laboratorium.

Pertanyaan riset yang sesuai: *bisakah CSI WiFi komoditas mendeteksi okupansi
ruang kelas nyata tanpa mengendalikan penghuninya?*

### 12.3. Isi dataset

10 sesi × 3–4 board × ~6 menit. Semua `sig_len=114`, ~36–44 paket/detik,
256 subcarrier (244 aktif).

- `count_s10` = **ruangan KOSONG** 290 detik, direkam 15:19 setelah kelas bubar.
  Satu-satunya baseline kosong yang ada.
- `count_s01` board `bf` mati setelah 11 detik; `count_s02` tanpa `bf` sama
  sekali. Keduanya efektif 3 board.
- `count_s07` nol transisi; `count_s09` semua event selesai di detik 19.5.

Penempatan board per zona (dikonfirmasi pengguna dari pengukuran ruangan):

| Zona | Board |
|---|---|
| A | `d0` |
| B | `bf` |
| C | `38` |
| D | `4b` |

**`COUNTING_RUNBOOK.md` §Denah zona SALAH** — di sana A=`38` dan C=`d0`,
tertukar. B dan D benar. Sumber kebenaran: `loader.DS_14_9.zone_board` di
`ml_people_count/src/csi_occupancy/datasets.py`.

> Sejak 2026-09-19 denah zona **tidak lagi** konstanta global `ZONE_BOARD`.
> Tiap dataset punya denahnya sendiri di objek `loader.Dataset`, karena
> `data-15-9` adalah ruangan lain dengan denah berbeda. Lihat §13.2.

### 12.4. Hasil analisis ruangan 1 — tiga pertanyaan, tiga jawaban

> **DIREVISI 2026-09-19 oleh §13.4.** Angka di bawah tetap benar sebagai
> deskripsi ruangan 1, tapi klaim "deteksi BERHASIL" di sini **belum melalui
> kontrol kelas-mayoritas dan kontrol jam** yang dijalankan di §13.4. Yang
> bertahan setelah kontrol itu adalah koherensi temporal (§13.5), bukan effect
> size fitur level di bawah. Baca §13.4-13.5 sebelum mengutip bagian ini.

**Deteksi okupansi (kosong vs berpenghuni): BERHASIL.**
12 dari 24 fitur |Cohen's d| > 0.8, 7 fitur > 1.5. Terkuat `bf_rssi_mean`
(d = −6.1). Sepuluh dari 24 fitur bernilai **di luar rentang seluruh sembilan
sesi berpenghuni**, jadi bukan sekadar hanyutan kanal. Catatan: hanya ada SATU
sesi kosong, direkam ~30 menit setelah sesi berpenghuni terakhir.

**Penghitungan jumlah orang: BELUM.**
Label melompat 0 → 7–16 tanpa apa pun di antaranya. Random forest menebak
**sesi** dari fitur CSI dengan akurasi 96.6% (acak 10%); median |korelasi|
terhadap jumlah orang turun 0.288 → 0.036 begitu efek sesi dibuang.

**Penghitungan per zona: BELUM.**
Semua korelasi board–zona |r| < 0.20; pasangan cocok menurut denah lebih kuat
hanya di 3 dari 6 statistik (setara lempar koin). Sebabnya isi zona tak berubah
dalam satu sesi, dan zona B praktis tak pernah terisi (rata-rata 0.11 orang).

### 12.5. Aturan analisis yang tidak boleh dilanggar

1. **Jangan pernah membagi train/test acak per jendela.** Pakai sesi sebagai
   grup. Jendela bersebelahan sangat berkorelasi, dan tiap sesi punya sidik jari
   kanal sendiri — model bisa berakurasi tinggi hanya dengan mengenali sesi lalu
   menyebut okupansi sesi itu.
2. **Ukur kegunaan sesi lewat `span_real_s`**, bukan jumlah event. `count_s09`
   punya 26 event tapi semuanya selesai dalam 20 detik dari 352 detik.
3. **Fitur berbasis SEBARAN (std/variance) yang membawa informasi**, bukan
   level rata-rata. `amp_mean` dan `rssi_mean` tidak pernah signifikan di uji
   transisi — sejalan dengan temuan lokalisasi (variance 79% vs amplitudo 36%).
4. **Board yang mati jangan dipakai memotong rentang waktu sesi.** Irisan naif
   "semua board hidup" pernah membuang 97% `count_s01` tanpa pesan error.
   `window_features()` membuangnya lewat `min_span_frac`.

### 12.6. Pengambilan data berikutnya — yang REALISTIS di kelas nyata

Urut menurut nilai per usaha:

1. **Lebih banyak sesi ruangan kosong.** Satu-satunya hal yang sepenuhnya bisa
   dikendalikan: sebelum kelas, sesudah kelas, jam istirahat, hari tanpa jadwal.
   Masing-masing 5 menit, tidak butuh kerja sama siapa pun. Empat-lima sesi di
   waktu dan hari berbeda langsung memperkuat hasil utama, karena memisahkan
   "kosong" dari "kondisi kanal jam sekian" — caveat terbesar saat ini.
2. **Rekam 10 menit SEBELUM kelas mulai dan 10 menit SESUDAH bubar.** Kelas
   punya transisi okupansi alami: mahasiswa datang bertahap, lalu pergi
   bertahap. Ini memberi ramp 0→16 dan 16→0 yang sesungguhnya — "tangga" yang
   diberikan jadwal kuliah, bukan instruksi. Kemungkinan besar ini perubahan
   paling berharga dari seluruh daftar, dan hanya berupa mengubah jendela
   perekaman.
3. **Kelas dengan ukuran berbeda** (seminar 5 orang vs kuliah 30 orang). Memberi
   variasi jumlah orang antar sesi tanpa mengatur siapa pun.
4. **Zona: biarkan atau ambil gratis.** Kalau mahasiswa selalu duduk di C dan D,
   counting per zona memang tak terjawab di ruangan ini — tulis itu sebagai
   temuan tentang ruangannya. Kalau pola duduk berbeda antar kelas, catat saja
   di mana mereka duduk tiap kali dan data zona terkumpul sendiri.

> **Catatan metodologis.** Periode datang/pergi berarti orang BERGERAK, yang
> mempengaruhi CSI secara berbeda dari orang DUDUK. Perlakukan ini sebagai sifat
> masalah, bukan derau: "mendeteksi perubahan okupansi" dan "mendeteksi okupansi
> tetap" mungkin dua tugas berbeda, dan punya keduanya di dataset itu aset.

### 12.7. Framing skripsi (versi 14-9, DIGANTI oleh §13.6)

> **Sudah tidak dipakai.** Ditulis saat hanya ada ruangan 1. Framing yang berlaku
> ada di §13.6. Disimpan karena alasan di butir "96.6% itu bahan tulisan" masih
> valid dan dipakai ulang di sana.

**Pertanyaan riset:** bisakah CSI WiFi komoditas mendeteksi okupansi ruang kelas
nyata yang sedang dipakai, **tanpa mengendalikan penghuninya?**

- **Diklaim sebagai hasil:** deteksi okupansi (kosong vs berpenghuni). Sertakan
  caveat apa adanya: hanya satu sesi kosong, direkam ~30 menit setelah sesi
  berpenghuni terakhir.
- **Dilaporkan terbuka, berikut alasannya:** penghitungan jumlah orang dan
  penghitungan per zona.
- **Angka 96.6% itu bahan tulisan, bukan aib.** Banyak literatur di bidang ini
  mengevaluasi dengan pembagian acak per jendela lalu melaporkan akurasi yang
  menggelembung. Kemampuan menebak *sesi* sebesar 96.6% adalah bukti konkret
  kenapa evaluasi seperti itu tidak sah — tulis sebagai temuan metodologis.
- **Aturan yang tidak bisa ditawar:** jangan pernah membagi train/test acak per
  jendela; selalu pakai sesi sebagai grup.

### 12.8. Cara menjalankan ulang analisis

Isi `ml_people_count/`:

| Berkas | Peran |
|---|---|
| `src/csi_occupancy/datasets.py` | baca `.bin`, rekonstruksi waktu, join label, fitur per jendela (dulu `loader.py`) |
| `src/csi_occupancy/paths.py` | satu-satunya tempat yang tahu lokasi file |
| `src/csi_occupancy/coherence.py` | **HASIL UTAMA**: koherensi temporal |
| `src/csi_occupancy/session_level.py` | tingkat sesi kedua ruangan, fitur flux |
| `src/csi_occupancy/eda_windows.py` | EDA per jendela + kontrol null (dulu `eda_15_9.py`) |
| `notebooks/nb_cells.py` | **sumber** notebook, Python biasa yang memanggil `md()` / `code()` |
| `notebooks/build_nb.py` | render `nb_cells.py` -> `eda_people_count.ipynb` |
| `notebooks/eda_people_count.ipynb` | 58 sel, ruangan 1 saja, MENDAHULUI temuan koherensi |
| `data/raw/` | data mentah 1.4 GB, hanya dibaca |
| `data/processed/` | cache fitur, boleh dihapus |
| `results/tables/`, `results/figures/` | keluaran analisis |
| `tests/` | 25 tes, menjaga kegagalan yang senyap |

> **Direstrukturisasi 2026-09-19.** Dulu semuanya datar di `ml_people_count/`.
> Paket dipasang dengan `python -m pip install -e ".[dev]"` sekali, lalu semua
> skrip dijalankan sebagai modul. Tidak ada lagi `sys.path` di skrip analisis.

**Ubah notebook lewat `nb_cells.py`, JANGAN edit `.ipynb` langsung**, lalu
`python build_nb.py` dan eksekusi ulang. Alasannya: diff `.ipynb` tidak terbaca
manusia, jadi review dan riwayat versi jadi tidak berguna tanpa sumber teks.

```powershell
cd ml_people_count
otebooks
python build_nb.py
python -c "import nbformat; from nbclient import NotebookClient; nb=nbformat.read('eda_people_count.ipynb',as_version=4); NotebookClient(nb,timeout=2400,kernel_name='python3',resources={'metadata':{'path':'.'}}).execute(); nbformat.write(nb,'eda_people_count.ipynb')"
```

Dua jebakan saat menulis `nb_cells.py`: isi sel berupa string `r"""..."""`,
jadi docstring `"""` di dalam sel kode akan **menutup sel itu lebih awal**
(pakai komentar `#`); dan `build_nb.py` harus mempertahankan `\n` di tiap baris
sumber, kalau tidak seluruh sel menyatu jadi satu baris saat dieksekusi.

`loader.window_features(session, win_s=2.0, hop_s=1.0, normalize=..., ds=...)`
adalah pintu masuk utama. `normalize` menerima `"none"`, `"session"`, dan
`"empty"` (relatif terhadap sesi kosong dataset yang dipakai) — lihat
docstring-nya untuk kapan memakai yang mana. Argumen `ds` memilih ruangan;
default `DS_14_9` supaya notebook lama tetap jalan. Lihat §13.2.

---

## 13. Dataset kedua `data-15-9` dan temuan koherensi temporal

> Ditambahkan 2026-09-19. Bagian ini **merevisi** §12.4 dan **mengganti** §12.7.
> Skrip analisisnya di `ml_people_count/src/csi_occupancy/`: `eda_windows.py`,
> `session_level.py`, `coherence.py`. Jalankan sebagai modul, mis.
> `python -m csi_occupancy.coherence`, atau `make all`.

### 13.1. `data-15-9` adalah RUANG KELAS YANG BERBEDA

**Fakta terpenting di bagian ini, dan tidak bisa disimpulkan dari file mana pun.**
Sembilan sesi `count_2_1`–`count_2_9` direkam 2026-09-15 pukul 12:36–14:28 di
**ruang kelas lain**, bukan ulangan ruangan `data-14-9`. Ukuran kelas ~1.5–2x
lebih besar (plateau 45–72 orang); jumlah pasti tidak tercatat, nilai plateau
label dipakai apa adanya.

Konsekuensi yang mengikat seluruh analisis:

1. **Fitur CSI dua dataset TIDAK BOLEH digabung** jadi satu set latih. Itu
   mencampur efek ruangan dengan efek jumlah orang. Bukti bahwa ini nyata:
   korelasi `4b_sub_std_spatial` vs jumlah orang adalah −0.92 dan −0.90 **di
   dalam** masing-masing ruangan, tapi **+0.07** kalau keduanya digabung.
2. Yang dilaporkan adalah **replikasi**: hasil per ruangan, lalu kesamaan arah
   antar ruangan sebagai buktinya.
3. Framing "ruangan 1 sepi vs ruangan 2 padat" memberi LOSO 0.999 tapi **TIDAK
   SAH** — ruangan dan tingkat keramaian kolinier sempurna.

Kondisi teknis `data-15-9` lebih baik: **keempat board merekam di 9 dari 9 sesi**
dengan ukuran file sebanding. Masalah board mati di `count_s01`/`count_s02` tidak
terulang.

### 13.2. Denah zona berbeda, dan cara kode menanganinya

| Zona | Ruangan 1 (`data-14-9`) | Ruangan 2 (`data-15-9`) |
|---|---|---|
| A | `d0` | `d0` |
| B | `bf` | `bf` |
| C | `38` | **`4b`** |
| D | `4b` | **`38`** |

C dan D **tertukar** antar ruangan. Karena frame `.bin` tidak punya version
field, denah yang usang menghasilkan angka zona salah **tanpa pesan error apa
pun**. Karena itu denah sekarang ikut di objek dataset, bukan konstanta global:

```python
import loader
loader.DS_14_9    # ruangan 1: C=38 D=4b, sesi kosong count_s10
loader.DS_15_9    # ruangan 2: C=4b D=38, sesi kosong count_2_9
f = loader.window_features("count_2_4", ds=loader.DS_15_9)
```

`DATA_DIR`, `ZONE_BOARD`, `EMPTY_SESSION` **masih ada** sebagai nama lama yang
menunjuk ke `DS_14_9`, supaya `nb_cells.py` dan notebook lama jalan tanpa diubah.
Sudah diverifikasi: output `count_s07`, `count_s01`, `count_s10` identik secara
numerik sebelum dan sesudah refactor, termasuk `normalize="empty"`. Satu-satunya
perubahan adalah kolom baru `dataset`.

Cache baseline kosong sekarang di-key pada **nama dataset**, bukan `data_dir`.
Sebelumnya itu jalur nyata untuk baseline ruangan 1 bocor ke ruangan 2.

### 13.3. Label `data-15-9` dicatat LIVE — ledakan awal itu kelambatan input

Semua sesi dicatat live. Ledakan event di detik-detik awal adalah **input manual
yang menyusul** mahasiswa yang sudah masuk, **bukan** hitungan statis yang
diketikkan di t=0.

- `count_2_1`..`count_2_5`: 78–82 event tersebar 5–10 menit, dengan exit nyata
  (`count_2_1`: 67 enter / 15 exit, event terakhir t=632 s).
- `count_2_6`..`count_2_9`: seluruh event di ~25 detik pertama; 2_6 dan 2_7 tanpa
  exit sama sekali.

**Cara memakainya:** label tetap berubah terhadap waktu — jangan diringkas jadi
satu N konstan per sesi. Yang tidak bisa dipercaya hanya **timestamp DI DALAM
ledakan awal**; nilai akhirnya benar. Analisis tingkat sesi karena itu memakai
plateau saja (buang 120 detik pertama).

`count_2_9` adalah sesi nyaris kosong (90% span di total=0) — padanan `count_s10`
untuk ruangan 2.

### 13.4. Kontrol null: kenapa hampir semua hasil "positif" runtuh

**Ini temuan metodologis utama proyek ini, dan lebih penting daripada angka
akurasi mana pun.** Ketiga pertanyaan riset awalnya tampak POSITIF dengan ukuran
biasa, dan ketiganya runtuh di bawah kontrol yang benar.

| Uji | Hasil naif | Setelah kontrol |
|---|---|---|
| Deteksi (LOSO) | akurasi **0.933** | = **persis kelas mayoritas**; `count_2_9`, satu-satunya sesi dengan jendela kosong, dapat **0.000**. Model menebak "terisi" untuk semuanya. |
| Counting dalam sesi | `count_2_1` MAE 4.10 vs baseline 5.69 | null **label-digeser-sirkuler** justru LEBIH mudah diprediksi (3.64) → itu autokorelasi, bukan penginderaan |
| Counting antar sesi | — | RF MAE **8.09** vs baseline rata-rata **9.37** (sd label 10.7) |
| Zona | denah pengguna > rata-rata sisanya | di antara **24 permutasi**: peringkat 8/24, 4/24, 3/24, 20/24. Permutasi terbaik untuk `rssi_std` justru denah ruangan 1 yang SALAH di sini. |
| Fitur level per sesi | rho −0.92 / −0.90, replikasi, permutation p=0.0025 | `corr(jam, N)` = +0.98 dan +0.83; setelah jam di-partial-out rho jatuh ke **−0.36 / −0.31** |

Tiga kontrol yang wajib dipakai seterusnya:

1. **Null label-digeser-sirkuler** untuk klaim apa pun di dalam satu sesi.
   Menggeser label secara sirkuler mempertahankan distribusi DAN autokorelasinya,
   tapi menghancurkan kaitannya ke CSI. Skill yang nyata harus mengalahkan ini.
2. **Bandingkan ke kelas mayoritas** dan lihat rincian per sesi untuk klaim
   klasifikasi. Akurasi agregat menyembunyikan model yang menebak satu kelas.
3. **Partial-out jam mulai sesi** untuk klaim tingkat sesi. Sesi direkam
   berurutan sementara ruangan terisi, jadi okupansi dan jam nyaris tak
   terpisahkan.

Catatan yang membaik: akurasi menebak **sesi** turun **96.6% → 71.7%** di ruangan
2, jadi sidik jari per-sesi lebih lemah di sana.

### 13.5. HASIL UTAMA: okupansi menambah variance BERSTRUKTUR WAKTU

Ini temuan terkuat dan paling bisa ditafsirkan dari kedua dataset. Diukur sebagai
autokorelasi lag-k amplitudo per subcarrier, dirata-rata atas subcarrier aktif,
hanya jendela plateau. Skrip: `coherence.py`.

| Lag | r1 kosong | r1 N=16 | r2 kosong | r2 N=72 |
|---|---|---|---|---|
| 1 paket | +0.07 | +0.56 | +0.16 | +0.68 |
| ~1 s (40) | +0.06 | +0.40 | +0.02 | +0.51 |
| ~5 s (200) | +0.02 | +0.24 | +0.01 | +0.35 |
| ~20 s (800) | +0.01 | +0.05 | −0.00 | +0.21 |

**Ruangan kosong kehilangan korelasi dalam 1–2 paket lalu datar** → variasinya
bebas antar-sampel, yaitu derau penerima/termal. **Ruangan berpenghuni bertahan
berkorelasi ratusan paket** → variasinya proses fisik dengan skala waktu sendiri:
tubuh bergeser, bergerak, bernapas.

Pemisahan koherensi@1s di **19 sesi, TANPA tumpang-tindih**:

- 17 sesi berpenghuni: **0.356 – 0.572** (mean 0.495)
- 2 sesi kosong: **0.146** (`count_s10`) dan **0.052** (`count_2_9`)
- rasio **5.0x**; kosong maksimum (0.146) < berpenghuni minimum (0.356)
- Mann-Whitney **p=0.0058**; berlaku di kedua ruangan secara independen

**Kenapa ini menjelaskan temuan lama.** `sub_var` (variance biasa) lemah dan
`amp_mean` nyaris buta — sejalan dengan temuan lokalisasi (variance 79% vs
amplitudo 36%). Sebabnya sekarang jelas: **variance saja tidak bisa membedakan
derau dari struktur.** Ruangan kosong dan berpenghuni punya variance sebanding;
yang membedakan adalah apakah variance itu punya SKALA WAKTU.

**Artefak yang sudah disingkirkan:**

- *Bukan laju paket.* 31–43 Hz di semua sesi, jadi 40 paket ≈ 1 s di semuanya.
- *Bukan SNR/noise floor.* **14 dari 17** sesi berpenghuni RSSI-nya LEBIH LEMAH
  daripada sesi kosong, tapi koherensinya tetap 0.356–0.572 (3–8x lebih tinggi).
  Amplitudo rata-rata setara (20.4 kosong vs 19.9 berpenghuni).
- *Nyaris bebas confound jam.* corr(koherensi, jam) = +0.25 dan −0.45 — kontrol
  yang mematikan semua fitur level, dan koherensi lolos.

**Yang tetap TIDAK terjawab:** di antara sesi berpenghuni saja, koherensi vs
jumlah orang rho=+0.16 (r1) dan −0.22 (r2), keduanya tidak signifikan.
**Kehadiran terdeteksi, JUMLAH ORANG tidak.**

**Caveat wajib:** hanya ada **2 sesi kosong**, satu per ruangan, masing-masing
direkam di waktu berbeda dari sesi berpenghuni ruangan itu. Pemisahan tanpa
tumpang-tindih dan argumen mekanismenya kuat, tapi sampel kosong tetap n=2.

### 13.5b. Arah kedua: laju fluktuasi vs ukuran kerumunan (sugestif)

Fitur **dinamika** (`flux` = mean|selisih 1 langkah| / mean level, langkah ~1 s).
Karena berupa selisih, drift skala jam hilang dengan sendirinya. Skrip:
`session_level.py`.

- **16 dari 18** korelasi flux-vs-N bertanda POSITIF di kedua ruangan, binomial
  **p=0.0007**. Makin ramai, makin cepat CSI berfluktuasi — prediksi berarah.
- `38_rssi_mean_flux` (+0.70/+0.66) dan `38_sub_var_flux` (+0.54/+0.59) replikasi
  lintas ruangan dengan tanda sama; permutation p=0.0105.
- **Caveat:** partial correlation terhadap jam lolos di ruangan 1 (+0.63, +0.65,
  +0.58) tapi **negatif** di ruangan 2. Jadi **sugestif, belum tuntas.**

Tingkat sesi adalah unit yang benar-benar disampel baik oleh kedua dataset: 19
sesi, N = 0..72 (ruangan 1 mengisi ujung sepi 0–16, ruangan 2 ujung padat 45–72).
Sendiri-sendiri rentangnya sempit; digabung jadi nyata.

### 13.5c. Tidak ada satu board yang jadi "sensornya"

Respons board tidak konsisten antar ruangan: `4b` terkuat di ruangan 1 (rho
+0.85), `bf` di ruangan 2 (+0.73), dan `d0` **berbalik tanda** (+0.65 → −0.51).
Digabung dengan hasil permutasi zona: CSI di sini membawa informasi okupansi
**tingkat ruangan**, bukan informasi **spasial** yang bisa dipercaya. Klaim
per-board tidak akan replikasi; klaim agregat-antar-board replikasi.

### 13.6. Framing skripsi yang berlaku (menggantikan §12.7)

**Pertanyaan riset tidak berubah:** bisakah CSI WiFi komoditas mendeteksi
okupansi ruang kelas nyata yang sedang dipakai, tanpa mengendalikan penghuninya?

Dua kontribusi, keduanya didukung data yang ada:

1. **Metodologis (paling kokoh).** Penginderaan okupansi CSI komoditas di
   ruangan tak terkendali didominasi confound yang disembunyikan oleh evaluasi
   standar. Buktinya konkret dan semuanya dari data sendiri: classifier sesi
   96.6%, detektor yang persis menyamai kelas mayoritas sementara satu-satunya
   sesi kosongnya dapat 0.000, null label-digeser yang mengalahkan label asli,
   denah zona yang cuma peringkat 8/24, dan korelasi kuat yang lenyap setelah
   kontrol jam. Sebagian besar literatur akan melaporkan beberapa di antaranya
   sebagai keberhasilan.

2. **Empiris — deteksi lewat struktur waktu (§13.5).** Okupansi menambah
   variance yang berstruktur waktu, terpisah tanpa tumpang-tindih di 19 sesi dua
   ruangan, dengan mekanisme yang bisa dijelaskan dan artefak yang sudah
   disingkirkan. Sertakan caveat n=2 sesi kosong.

Dilaporkan terbuka berikut alasannya: **penghitungan jumlah orang** dan
**penghitungan per zona**. Arah flux (§13.5b) ditulis sebagai sugestif.

- **Angka 96.6% itu bahan tulisan, bukan aib** — alasan di §12.7 tetap berlaku.
- **Aturan yang tidak bisa ditawar:** jangan pernah membagi train/test acak per
  jendela; selalu pakai sesi sebagai grup; jangan pernah menggabung dua ruangan.

### 13.7. Pengambilan data berikutnya — satu hal yang paling penting

**Rekam SATU kali tanpa memutus perekaman, melintasi bubarnya kelas:** ruangan
penuh → mahasiswa keluar bertahap → ruangan kosong, dalam satu file utuh.

Kedua dataset gagal karena sebab struktural yang SAMA: **satu sesi = satu tingkat
okupansi yang nyaris konstan**, sehingga "kosong vs terisi" dan "N vs M orang"
selalu jadi perbandingan *antar-sesi*, tak terpisahkan dari waktu, drift kanal,
dan identitas sesi. Di `data-15-9`, **316 dari 336** jendela kosong berasal dari
`count_2_9` saja; sesi lain menyumbang 1–11 jendela di detik-detik awalnya.

Tidak ada model yang bisa menambal ini. Satu perekaman kontinu melintasi
bubarnya kelas langsung mengubah deteksi dari klaim antar-sesi yang confounded
menjadi klaim **dalam satu sesi**, dan sekaligus memberi ramp N→0 yang nyata
untuk counting. Biayanya satu perekaman; kalau baru disadari setelah
pengumpulan, yang hangus satu hari penuh.

Urutan berikutnya setelah itu: (2) beberapa sesi kosong di jam dan hari berbeda,
supaya "kosong" bukan satu titik waktu; (3) kelas dengan ukuran berbeda;
(4) untuk klaim zona, catat di mana mahasiswa duduk tiap sesi — zona saat ini
naik bersamaan (`corr(C, total)` = +0.85), jadi tidak terpisahkan.
