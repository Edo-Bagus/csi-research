# tools/legacy_uart — TIDAK DIPAKAI LAGI

Skrip di sini untuk jalur **UART biner era lama** (header 28 B, `msg_id`/`tx_id`).
Sistem sekarang memakai **TCP over Wi-Fi** dengan header 50 B.

**Jangan pakai skrip ini untuk data v2** — struct-nya beda, hasilnya akan terparsing
tapi isinya sampah (frame tidak punya version field, jadi tidak ada error).

Tools yang benar ada di `tools/`:
`csi_collector.py`, `csi_merge.py`, `simulate_node.py`.

Disimpan hanya sebagai referensi historis; lihat KNOWLEDGE.md §5.
