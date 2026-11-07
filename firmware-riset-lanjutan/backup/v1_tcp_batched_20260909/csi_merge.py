#!/usr/bin/env python3
"""Gabungkan .bin multi-node dari csi_collector.py menjadi satu CSV.

Menerapkan skema alignment (a): tiap node independen, penyelarasan lewat binning
timestamp host. Keluaran default adalah satu baris per paket per node
(long format), dengan kolom `bin` sebagai kunci penyelarasan antar node.

PENTING soal makna `bin`: dua baris dengan `bin` sama BUKAN berarti kedua board
mengamati paket yang sama. Tiap board nge-ping router sendiri-sendiri, jadi
paketnya memang berbeda -- yang sama hanya jendela waktunya. Untuk korespondensi
paket sungguhan dibutuhkan skema (b)/(c); lihat KNOWLEDGE.md.

Pemakaian:
    python csi_merge.py capture/sesi1 -o sesi1.csv
    python csi_merge.py capture/sesi1 -o sesi1.csv --bin-ms 100 --expand-csi
    python csi_merge.py capture/sesi1 --stats-only
"""

import argparse
import csv
import glob
import os
import struct
import sys
from collections import defaultdict

HEADER_STRUCT = struct.Struct("<I B 6s h B b b B B B 6s I Q H B H")
RECORD_PREFIX = struct.Struct("<dI")

FIELDS = ["seq", "node_id", "node_mac", "rssi", "rate", "noise_floor",
          "fft_gain", "agc_gain", "channel", "first_word_invalid", "ap_mac",
          "timestamp", "uptime_us", "sig_len", "rx_state", "len"]


def mac_str(raw):
    return ":".join(f"{b:02x}" for b in raw)


def read_bin(path):
    """Yield dict per record dari satu file .bin."""
    with open(path, "rb") as f:
        data = f.read()
    i = 0
    n = len(data)
    while i + RECORD_PREFIX.size <= n:
        host_time, payload_len = RECORD_PREFIX.unpack_from(data, i)
        i += RECORD_PREFIX.size
        if i + payload_len > n:
            # File terpotong (mis. kolektor dibunuh saat menulis). Abaikan sisa.
            break
        fields = HEADER_STRUCT.unpack_from(data, i)
        csi_len = fields[-1]
        csi = struct.unpack_from(f"<{csi_len}h", data, i + HEADER_STRUCT.size)
        i += payload_len

        rec = dict(zip(FIELDS, fields))
        rec["node_mac"] = mac_str(rec["node_mac"])
        rec["ap_mac"] = mac_str(rec["ap_mac"])
        rec["host_time"] = host_time
        rec["csi"] = csi
        yield rec


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("indir", help="folder berisi .bin dari csi_collector.py")
    ap.add_argument("-o", "--out", help="file CSV keluaran")
    ap.add_argument("--bin-ms", type=float, default=100.0,
                    help="lebar jendela penyelarasan dalam ms (default 100)")
    ap.add_argument("--expand-csi", action="store_true",
                    help="pecah CSI jadi kolom csi_0..csi_N (file jadi besar)")
    ap.add_argument("--stats-only", action="store_true",
                    help="hanya tampilkan ringkasan, tidak menulis CSV")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.indir, "*.bin")))
    if not files:
        print(f"tidak ada .bin di {args.indir}", file=sys.stderr)
        return 1

    records = []
    per_node = defaultdict(list)
    for path in files:
        for rec in read_bin(path):
            records.append(rec)
            per_node[rec["node_mac"]].append(rec)

    if not records:
        print("tidak ada record terbaca", file=sys.stderr)
        return 1

    records.sort(key=lambda r: r["host_time"])
    t0 = records[0]["host_time"]
    bin_s = args.bin_ms / 1000.0
    for r in records:
        r["t_rel"] = r["host_time"] - t0
        r["bin"] = int(r["t_rel"] / bin_s)

    # Ringkasan: yang paling penting adalah berapa bin yang benar-benar berisi
    # data dari SEMUA node -- itulah yang bisa dipakai untuk fitur multi-view.
    n_nodes = len(per_node)
    bins = defaultdict(set)
    for r in records:
        bins[r["bin"]].add(r["node_mac"])
    full = sum(1 for v in bins.values() if len(v) == n_nodes)

    print(f"File          : {len(files)}")
    print(f"Total record  : {len(records)}")
    print(f"Node          : {n_nodes}")
    for mac, rs in sorted(per_node.items()):
        span = rs[-1]["host_time"] - rs[0]["host_time"]
        rate = len(rs) / span if span > 0 else 0
        seqs = [r["seq"] for r in rs]
        lost = (max(seqs) - min(seqs) + 1) - len(seqs)
        rssi = [r["rssi"] for r in rs]
        print(f"  node {mac}: {len(rs)} paket, {rate:.1f} pkt/s, "
              f"hilang={lost}, rssi {min(rssi)}..{max(rssi)}")
    print(f"Durasi        : {records[-1]['t_rel']:.1f} s")
    print(f"Bin {args.bin_ms:.0f} ms   : {len(bins)} terisi, "
          f"{full} berisi semua {n_nodes} node "
          f"({100.0*full/len(bins) if bins else 0:.1f}%)")

    if args.stats_only:
        return 0
    if not args.out:
        print("\n(--out tidak diberikan; tidak menulis CSV)")
        return 0

    max_len = max(r["len"] for r in records)
    base = ["bin", "t_rel", "host_time"] + FIELDS
    if args.expand_csi:
        cols = base + [f"csi_{i}" for i in range(max_len)]
    else:
        cols = base + ["csi"]

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in records:
            row = {k: r[k] for k in base}
            row["t_rel"] = f"{r['t_rel']:.6f}"
            row["host_time"] = f"{r['host_time']:.6f}"
            if args.expand_csi:
                for i, v in enumerate(r["csi"]):
                    row[f"csi_{i}"] = v
            else:
                row["csi"] = " ".join(str(v) for v in r["csi"])
            w.writerow(row)

    size_mb = os.path.getsize(args.out) / (1024 * 1024)
    print(f"\nDitulis {len(records)} baris -> {args.out} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
