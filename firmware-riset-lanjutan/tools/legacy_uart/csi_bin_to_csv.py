#!/usr/bin/env python3
import argparse
import csv
import os
import struct
import sys

MAGIC = b"\xef\xbe\xad\xde"  # 0xDEADBEEF little-endian
HEADER_STRUCT = struct.Struct("<I B h B b b B B B 6s I H B H")

BASE_FIELDS = [
    "msg_id",
    "tx_id",
    "rssi",
    "rate",
    "noise_floor",
    "fft_gain",
    "agc_gain",
    "channel",
    "first_word_invalid",
    "mac",
    "timestamp",
    "sig_len",
    "rx_state",
    "len",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse CSI .bin to .csv.")
    parser.add_argument("bin", help="Input .bin file")
    parser.add_argument("-o", "--out", default="", help="Output .csv file path")
    parser.add_argument("--max-csi-len", type=int, default=1024, help="Max CSI length")
    parser.add_argument(
        "--expand-csi",
        action="store_true",
        help="Write fixed columns csi_0..csi_{max-1} (else single 'csi' column)",
    )
    parser.add_argument("--quiet", action="store_true", help="Disable progress output")
    return parser.parse_args()


def mac_to_str(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02x}" for b in mac_bytes)


def main() -> int:
    args = parse_args()

    if not os.path.isfile(args.bin):
        print(f"Input not found: {args.bin}", file=sys.stderr)
        return 1

    out_path = args.out
    if not out_path:
        base, _ = os.path.splitext(args.bin)
        out_path = base + ".csv"

    with open(args.bin, "rb") as f:
        data = f.read()

    if args.expand_csi:
        fieldnames = BASE_FIELDS + [f"csi_{i}" for i in range(args.max_csi_len)]
    else:
        fieldnames = BASE_FIELDS + ["csi"]

    rows = 0
    bad = 0
    magic_count = 0
    idx = 0
    data_len = len(data)

    with open(out_path, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()

        while idx + 4 <= data_len:
            if data[idx:idx + 4] == MAGIC:
                magic_count += 1
                idx += 4
                continue

            if idx + HEADER_STRUCT.size > data_len:
                break

            header = HEADER_STRUCT.unpack_from(data, idx)
            (
                msg_id,
                tx_id,
                rssi,
                rate,
                noise_floor,
                fft_gain,
                agc_gain,
                channel,
                first_word_invalid,
                mac_raw,
                timestamp,
                sig_len,
                rx_state,
                csi_len,
            ) = header

            if csi_len == 0 or csi_len > args.max_csi_len:
                next_magic = data.find(MAGIC, idx + 1)
                if next_magic == -1:
                    break
                bad += 1
                idx = next_magic
                continue

            total_size = HEADER_STRUCT.size + (csi_len * 2)
            if idx + total_size > data_len:
                break

            csi = struct.unpack_from(f"<{csi_len}h", data, idx + HEADER_STRUCT.size)

            row = {
                "msg_id": msg_id,
                "tx_id": tx_id,
                "rssi": rssi,
                "rate": rate,
                "noise_floor": noise_floor,
                "fft_gain": fft_gain,
                "agc_gain": agc_gain,
                "channel": channel,
                "first_word_invalid": first_word_invalid,
                "mac": mac_to_str(mac_raw),
                "timestamp": timestamp,
                "sig_len": sig_len,
                "rx_state": rx_state,
                "len": csi_len,
            }

            if args.expand_csi:
                for i in range(args.max_csi_len):
                    row[f"csi_{i}"] = csi[i] if i < csi_len else ""
            else:
                row["csi"] = " ".join(str(v) for v in csi)

            writer.writerow(row)
            rows += 1
            idx += total_size

    if not args.quiet:
        print(
            f"Done. rows={rows}, magic={magic_count}, bad_records={bad}, out={out_path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
