#!/usr/bin/env python3
"""Tempelkan label okupansi per zona ke CSV hasil csi_merge.py.

Membaca `occupancy.csv` (dari mark_occupancy.py) dan sebuah CSV CSI yang punya
kolom `host_time`, lalu menambahkan kolom A,B,C,D,total ke tiap baris.

Kenapa join-nya lewat `host_time` dan BUKAN `t_rel`: csi_merge.py secara default
menulis `t_rel` dari jam board yang sudah dikoreksi offset, sedangkan label
dicatat dengan `time.time()` laptop. Keduanya berbeda beberapa milidetik sampai
puluhan milidetik. `host_time` adalah satu-satunya kolom yang benar-benar sama
jamnya di kedua sisi.

Pencocokannya adalah pencarian INTERVAL, bukan tetangga terdekat: keadaan
berlaku sejak tombol ditekan sampai tombol berikutnya. Memakai "penanda
terdekat" akan menggeser separuh tiap interval ke label yang salah.

Pemakaian:

    python tools\\csi_merge.py capture\\count_sesi1 -o sesi1.csv --bin-ms 100
    python tools\\label_occupancy.py sesi1.csv \\
        --occupancy capture\\count_sesi1\\occupancy.csv -o sesi1_labeled.csv

Baris CSI yang jatuh DI LUAR rentang label (mis. kolektor sudah jalan sebelum
pencatat label dimulai) dibuang secara default -- baris tanpa label adalah baris
yang tidak diketahui kebenarannya, bukan baris bernilai nol. Pakai --keep-unlabeled
kalau memang ingin melihatnya.
"""

import argparse
import bisect
import csv
import os
import sys

ZONES = ["A", "B", "C", "D"]
LABEL_COLS = ZONES + ["total"]


def load_occupancy(path):
    """Baca occupancy.csv -> (daftar t_start terurut, daftar interval).

    Interval: (t_start, t_end, {A,B,C,D,total}).
    """
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append((
                float(r["t_start"]),
                float(r["t_end"]),
                {k: int(r[k]) for k in LABEL_COLS},
            ))
    if not rows:
        raise SystemExit(f"{path}: tidak ada interval")
    rows.sort(key=lambda x: x[0])

    # Interval dari mark_occupancy.py bersambung rapat, tapi file hasil edit
    # tangan bisa saja tumpang tindih. Itu ambigu, jadi hentikan -- jangan
    # diam-diam pilih salah satu.
    for i in range(len(rows) - 1):
        if rows[i][1] > rows[i + 1][0] + 1e-6:
            raise SystemExit(
                f"{path}: interval tumpang tindih di t_start={rows[i + 1][0]:.6f}")
    return [r[0] for r in rows], rows


def lookup(starts, rows, t):
    """Keadaan yang berlaku pada waktu t, atau None kalau di luar rentang."""
    i = bisect.bisect_right(starts, t) - 1
    if i < 0:
        return None
    t0, t1, labels = rows[i]
    if t >= t1:
        return None          # jatuh di celah setelah interval terakhir
    return labels


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_in", help="CSV hasil csi_merge.py (harus ada kolom host_time)")
    ap.add_argument("--occupancy", required=True,
                    help="occupancy.csv dari mark_occupancy.py")
    ap.add_argument("-o", "--out", required=True, help="CSV keluaran")
    ap.add_argument("--keep-unlabeled", action="store_true",
                    help="jangan buang baris di luar rentang label "
                         "(kolom label dikosongkan)")
    args = ap.parse_args()

    starts, rows = load_occupancy(args.occupancy)
    t_lo, t_hi = rows[0][0], rows[-1][1]

    with open(args.csv_in, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        if "host_time" not in (rd.fieldnames or []):
            raise SystemExit(f"{args.csv_in}: tidak ada kolom host_time")
        cols = list(rd.fieldnames) + [c for c in LABEL_COLS if c not in rd.fieldnames]

        n_in = n_out = n_drop = 0
        # Lama-waktu per kelas dihitung dari BIN, bukan dari durasi interval:
        # yang menentukan keseimbangan dataset adalah jumlah sampel, dan bin
        # bisa hilang saat paket drop.
        hist = {}

        with open(args.out, "w", newline="", encoding="utf-8") as g:
            w = csv.DictWriter(g, fieldnames=cols)
            w.writeheader()
            for r in rd:
                n_in += 1
                lab = lookup(starts, rows, float(r["host_time"]))
                if lab is None:
                    n_drop += 1
                    if not args.keep_unlabeled:
                        continue
                    r.update({c: "" for c in LABEL_COLS})
                else:
                    r.update(lab)
                    hist[lab["total"]] = hist.get(lab["total"], 0) + 1
                w.writerow(r)
                n_out += 1

    print(f"Label   : {args.occupancy}  ({len(rows)} interval, "
          f"{t_hi - t_lo:.1f} s)")
    print(f"Masukan : {args.csv_in}  ({n_in} baris)")
    print(f"Keluaran: {args.out}  ({n_out} baris)")
    if n_drop:
        verb = "dikosongkan" if args.keep_unlabeled else "dibuang"
        pct = 100.0 * n_drop / n_in if n_in else 0
        print(f"  {n_drop} baris ({pct:.1f}%) di luar rentang label, {verb}.")
        if pct > 20:
            print("  ! lebih dari 20% tidak berlabel -- kemungkinan pencatat label "
                  "dijalankan jauh setelah kolektor, atau berhenti lebih dulu.")
    if hist:
        tot = sum(hist.values())
        print("Sebaran bin per total orang:")
        for k in sorted(hist):
            print(f"  {k} orang : {hist[k]:7d} bin  ({100.0*hist[k]/tot:5.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
