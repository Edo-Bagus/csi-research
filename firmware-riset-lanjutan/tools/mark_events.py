#!/usr/bin/env python3
"""Pencatat penanda waktu manual saat capture berjalan.

Dipakai berdampingan dengan `csi_collector.py` di terminal terpisah. Tiap kali
Enter ditekan, waktu `time.time()` dicatat ke CSV. Jam yang dipakai SAMA dengan
jam yang dibubuhkan kolektor ke tiap record (`host_time`), jadi penanda ini bisa
langsung disandingkan dengan data CSI tanpa kalibrasi apa pun.

Kenapa perlu: jalan memutar dengan tempo metronom sekalipun akan melenceng
beberapa persen per lap, dan kesalahan itu menumpuk. Delapan lap x 40 s = 320 s;
melenceng 3% saja sudah 10 detik di akhir -- seperempat lap, cukup untuk menggeser
label satu sudut penuh. Penanda per sudut membuat pemetaan waktu->posisi
dikoreksi ulang tiap lap, bukan diekstrapolasi dari awal.

Pemakaian (terminal #3, di samping kolektor):

    python tools\\mark_events.py --outdir capture\\loc_walk

    # urutan sudut khusus (default: urutan jalan searah 4b -> bf -> 38 -> d0)
    python tools\\mark_events.py --outdir capture\\loc_static --corners 4b,bf,38,d0

Tekan Enter tiap kali MELEWATI sudut. Ctrl-C untuk selesai.
"""

import argparse
import csv
import os
import sys
import time

# Urutan jalan yang disepakati: mulai di 4b (kanan-bawah), lalu bf (kanan-atas),
# 38 (kiri-atas), d0 (kiri-bawah), kembali ke 4b.
DEFAULT_CORNERS = ["4b", "bf", "38", "d0"]

# Peta sudut -> posisi, hanya untuk ditampilkan agar tidak salah tekan.
CORNER_DESC = {
    "4b": "kanan-bawah",
    "bf": "kanan-atas",
    "38": "kiri-atas",
    "d0": "kiri-bawah",
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", required=True,
                    help="folder sesi yang sama dengan --outdir kolektor")
    ap.add_argument("--corners", default=",".join(DEFAULT_CORNERS),
                    help="urutan sudut yang dilewati, dipisah koma "
                         f"(default {','.join(DEFAULT_CORNERS)})")
    ap.add_argument("--name", default="markers.csv",
                    help="nama file penanda (default markers.csv)")
    args = ap.parse_args()

    corners = [c.strip() for c in args.corners.split(",") if c.strip()]
    if not corners:
        print("daftar --corners kosong", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    path = os.path.join(args.outdir, args.name)
    if os.path.exists(path):
        # Satu sesi = satu folder. Menimpa penanda diam-diam akan menghasilkan
        # label yang tidak cocok dengan .bin di folder yang sama.
        print(f"SUDAH ADA: {path}", file=sys.stderr)
        print("Pakai --outdir baru, atau hapus file itu kalau capture diulang.",
              file=sys.stderr)
        return 1

    print(f"Penanda -> {path}")
    print(f"Urutan  : {' -> '.join(corners)} (berulang)")
    print()
    print("Tekan ENTER TEPAT saat melewati sudut. Ctrl-C untuk selesai.")
    print()

    rows = []
    t_start = time.time()
    i = 0
    try:
        # Baris pertama menandai awal capture, bukan sudut. Berguna kalau
        # penanda dimulai sebelum jalan.
        while True:
            nxt = corners[i % len(corners)]
            lap = i // len(corners) + 1
            desc = CORNER_DESC.get(nxt, "?")
            try:
                input(f"  lap {lap:2d}  berikutnya: {nxt} ({desc})  > ")
            except EOFError:
                break
            t = time.time()
            rows.append({
                "host_time": f"{t:.6f}",
                "t_rel": f"{t - t_start:.3f}",
                "idx": i,
                "lap": lap,
                "corner": nxt,
            })
            print(f"       tercatat t+{t - t_start:7.2f}s  {nxt}")
            i += 1
    except KeyboardInterrupt:
        print()

    if not rows:
        print("tidak ada penanda tercatat; tidak menulis file.")
        return 0

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["host_time", "t_rel", "idx", "lap", "corner"])
        w.writeheader()
        w.writerows(rows)

    span = float(rows[-1]["t_rel"]) - float(rows[0]["t_rel"])
    n_lap = len(rows) / len(corners)
    print(f"Ditulis {len(rows)} penanda -> {path}")
    print(f"Rentang {span:.1f} s, {n_lap:.2f} lap, "
          f"rata-rata {span / n_lap if n_lap else 0:.1f} s/lap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
