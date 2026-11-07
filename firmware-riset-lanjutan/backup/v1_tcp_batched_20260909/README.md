# Backup v1 — TCP streaming, versi ber-batching (2026-09-09)

Snapshot **sebelum** perbaikan timing/filtering. Disimpan supaya versi ini bisa
dikembalikan kalau perbaikan v2 ternyata bermasalah.

## Isi

| File | Keterangan |
|---|---|
| `app_main.c` | Firmware TCP v1 (batching 8 KB, tanpa filter sig_len) |
| `csi_collector.py` | Kolektor v1 |
| `csi_merge.py` | Merge v1 |
| `simulate_node.py` | Simulator v1 |
| `capture_sesi1_raw/` | **Data capture asli 2026-09-09 11:20**, 2 node, 59 detik |

## Cara revert

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2
copy backup\v1_tcp_batched_20260909\app_main.c main\app_main.c
copy backup\v1_tcp_batched_20260909\csi_collector.py tools\
copy backup\v1_tcp_batched_20260909\csi_merge.py tools\
idf.py build
idf.py -p COM15 flash
```

> **Perhatian:** format frame v1 dan v2 **berbeda**. Kolektor v2 tidak bisa membaca
> stream firmware v1 dan sebaliknya. Kalau revert, revert **firmware DAN tools
> bersama-sama**.

## Kenapa versi ini diganti

Tiga masalah terukur pada capture `capture_sesi1_raw/` (analisis 2026-09-09):

1. **Dua jenis paket tercampur.** `sig_len=114` (ICMP echo reply) dan `sig_len=94`
   (frame lain dari router) datang ~50/50, dengan distribusi amplitudo dan varians
   yang berbeda (CV 0.125 vs 0.296). Fitur ML jadi melihat bimodalitas yang
   penyebabnya jenis frame, bukan keberadaan orang.

2. **`host_time` rusak karena TCP batching.** Firmware menumpuk sampai 8 KB sebelum
   kirim, jadi ~8 paket mendapat timestamp host nyaris identik padahal ditangkap
   belasan-puluhan ms terpisah. Terukur: 70-77% paket datang <5 ms terpisah, median
   inter-arrival host 0.0 ms padahal menurut jam ESP 13 ms. Error timestamp steady
   state std 84 ms (node38) sampai 3200 ms (node4b) — lebih besar dari lebar bin
   150 ms, sehingga penyelarasan skema (a) tidak valid.
   Akibatnya coverage bin nyata hanya **53.2%**, bukan ~95% seperti di simulasi
   (simulator mengirim paket satu-satu sehingga tidak pernah memunculkan batching).

3. **Backlog startup mencemari awal rekaman.** Board mulai menangkap CSI sebelum
   kolektor hidup; `seq` tetap naik walau paket dibuang. Terukur: jam ESP merentang
   140.9 s sementara host hanya 59.3 s (lag 81 s), lalu backlog dikirim sekaligus
   dengan timestamp "sekarang".

**Yang TIDAK bermasalah di v1** (dan tetap dipertahankan di v2): konfigurasi radio,
akuisisi CSI, dan kualitas sinyalnya sendiri — 256 subcarrier, 9 subcarrier nol di
posisi guard band/DC yang benar, 0 paket duplikat, RSSI dua node terpisah jelas
(-34 vs -48 dBm). Masalahnya murni di lapisan transport dan timing.
