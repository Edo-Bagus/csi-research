# RISET_CSI_2 — Sistem pengumpulan CSI multi-STA (ESP32-C6)

Sistem pengumpulan Wi-Fi CSI **multi-node** untuk skripsi *people counting*.
N board ESP32-C6 memanen CSI dan mengirimkannya lewat **TCP ke laptop kolektor**.

- **Target:** ESP32-C6 · **ESP-IDF:** 5.5.2
- **Radio:** channel 11, 2,4 GHz, HT20, 802.11ax (HE) → 256 subcarrier
- **Router:** ASUS RT-AX53U, SSID `<SSID>`, gateway `192.168.50.1`
- **Kolektor:** laptop di `<IP_LAPTOP>:5566`

```
   ESP #1 ──┐
   ESP #2 ──┤
   ESP #3 ──┼── Wi-Fi/TCP ──> Router ──> Laptop (csi_collector.py)
   ESP #4 ──┘                             1 file .bin per node
```

**Tidak ada kabel USB saat capture** — USB hanya untuk flashing. Setelah di-flash,
board cukup diberi daya USB apa saja dan bisa ditaruh di mana saja di ruangan.

## Status: BEKERJA, terverifikasi 4 board

Capture nyata 2026-09-09 (29 detik, 4 board):

| Metrik | Hasil |
|---|---|
| Paket | 4389 |
| **Hilang** | **0 di keempat node** |
| `len` / `sig_len` | 512 / 114 di semua paket |
| Coverage bin 150 ms | **97,4%** (semua 4 node) |
| RSSI per node | −32 / −36 / −40 / −46 dBm |

**Satu binary untuk semua board.** `node_id` diturunkan dari MAC saat runtime, jadi
menambah board = flash binary yang sama, tanpa build ulang dan tanpa risiko salah
label dataset.

## Mulai

```powershell
# Build & flash (butuh baris PATH ini, lihat KNOWLEDGE.md)
$env:PATH = "$env:USERPROFILE\.espressif\tools\idf-python\3.11.2;" + $env:PATH
. C:\esp\v5.5.2\esp-idf\export.ps1
idf.py build
idf.py -p COM15 flash monitor

# Capture: jalankan kolektor DULU, baru nyalakan board
python tools\csi_collector.py --outdir capture\sesi4 -v

# Analisis
python tools\csi_merge.py capture\sesi4 --stats-only --bin-ms 100
python tools\csi_merge.py capture\sesi4 -o sesi4.csv --bin-ms 100
```

## Baca ini dulu

- **[RUNBOOK.md](RUNBOOK.md)** — prosedur capture langkah demi langkah. Ditulis untuk
  dipakai **saat offline**, karena router tidak punya WAN.
- **[KNOWLEDGE.md](KNOWLEDGE.md)** — konteks yang tidak terbaca dari kode: kenapa
  pemancarnya router, format frame biner, hasil pengukuran, dan utang teknis.

Tiga hal yang paling sering salah dipahami:

1. **Pemancarnya router, bukan ESP kedua.** `CSI_send*` di repo induk memakai ESP-NOW
   dan tidak dipakai sistem ini.
2. **Jalankan kolektor SEBELUM menyalakan board.** Kalau terbalik, board menangkap CSI
   yang tidak bisa dikirim ke mana-mana.
3. **Frame tidak punya version field.** Kalau struct di firmware diubah, ketiga skrip
   di `tools/` harus diubah serentak — ketidakcocokan menghasilkan data yang
   terparsing tapi isinya sampah, bukan error.

## Isi

```
main/app_main.c        firmware v2 (TCP streaming, satu-satunya sumber)
tools/csi_collector.py server TCP di laptop
tools/csi_merge.py     .bin multi-node -> CSV tersejajarkan
tools/simulate_node.py client ESP palsu, untuk uji tanpa hardware
tools/legacy_uart/     skrip era UART, TIDAK dipakai lagi
capture/               hasil capture (sesi1=v1, sesi2=v2 2 board, sesi3=v2 4 board)
backup/                snapshot v1 lengkap + data mentahnya, bisa di-revert
```
