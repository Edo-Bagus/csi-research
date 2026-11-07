#!/usr/bin/env python3
"""
Simulates the terminal output of csi_uart_capture.py using generated dummy data.

Packet format mirrors app_main.c / csi_bin_to_csv.py:
  MAGIC (4 bytes, every ~1 s)  +  N x [header (28 B) + csi_len * int16]

Header struct: "<I B h B b b B B B 6s I H B H"
  msg_id, tx_id, rssi, rate, noise_floor, fft_gain, agc_gain,
  channel, first_word_invalid, mac[6], timestamp, sig_len, rx_state, csi_len

Fault model
  --loss-rate   : per-packet drop probability (default 0.03 = 3%)
  --noise-rate  : per-byte corruption probability (default 0.001 = 0.1%)
  --seed        : RNG seed — same seed always produces identical output
"""

import argparse
import io
import random
import struct
import sys
import time

MAGIC         = b"\xef\xbe\xad\xde"
HEADER_STRUCT = struct.Struct("<I B h B b b B B B 6s I H B H")
TX_MAC        = bytes([0x1A, 0x00, 0x00, 0x00, 0x00, 0x00])

CHANNEL     = 11
TX_ID       = 4
PACKET_RATE = 100   # packets / second

# Valid CSI lengths for 802.11ax HE SU 20 MHz; driver can report any of these.
CSI_LEN_CHOICES = [234, 242, 256]


# ---------------------------------------------------------------------------
# Packet / stream generation
# ---------------------------------------------------------------------------

def make_packet(rng: random.Random, msg_id: int, elapsed_ms: int) -> bytes:
    csi_len            = rng.choice(CSI_LEN_CHOICES)
    rssi               = rng.randint(-72, -45)
    noise_floor        = rng.randint(-98, -90)
    fft_gain           = rng.randint(-4, 4)
    agc_gain           = rng.randint(20, 40)
    rate               = 0x14   # WIFI_PHY_RATE_MCS0_LGI
    sig_len            = 100
    rx_state           = 0
    first_word_invalid = 0
    timestamp          = elapsed_ms * 1000  # microseconds

    header = HEADER_STRUCT.pack(
        msg_id, TX_ID, rssi, rate, noise_floor, fft_gain, agc_gain,
        CHANNEL, first_word_invalid, TX_MAC,
        timestamp, sig_len, rx_state, csi_len,
    )
    csi_data = struct.pack(
        f"<{csi_len}h", *[rng.randint(-512, 511) for _ in range(csi_len)]
    )
    return header + csi_data


def apply_noise(rng: random.Random, data: bytes, noise_rate: float) -> tuple:
    """Randomly corrupt individual bytes to simulate UART line noise."""
    if noise_rate <= 0.0:
        return data, 0
    buf   = bytearray(data)
    count = 0
    for i in range(len(buf)):
        if rng.random() < noise_rate:
            buf[i] = rng.randint(0, 255)
            count += 1
    return bytes(buf), count


def generate_stream(
    rng: random.Random, duration: float, packet_rate: int, loss_rate: float
) -> tuple:
    """
    Returns (BytesIO stream, packets_generated, packets_dropped).
    msg_id increments even for dropped packets so gaps are visible in the CSV.
    """
    buf          = io.BytesIO()
    total_ms     = int(duration * 1000)
    interval_ms  = max(1, 1000 // packet_rate)
    magic_every  = 1000  # ms — matches UART_MAGIC_INTERVAL_MS in app_main.c

    last_magic_ms = -magic_every
    msg_id        = 0
    generated     = 0
    lost          = 0

    for t_ms in range(0, total_ms, interval_ms):
        if t_ms - last_magic_ms >= magic_every:
            buf.write(MAGIC)
            last_magic_ms = t_ms

        msg_id += 1
        if rng.random() < loss_rate:
            lost += 1
            continue  # packet never reaches the wire

        buf.write(make_packet(rng, msg_id, t_ms))
        generated += 1

    return buf, generated, lost


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def simulate(args: argparse.Namespace) -> int:
    duration = args.duration if args.duration > 0 else 10.0
    out_path = args.out
    rng      = random.Random(args.seed)  # single seeded instance controls everything

    min_pkt = HEADER_STRUCT.size + min(CSI_LEN_CHOICES) * 2
    max_pkt = HEADER_STRUCT.size + max(CSI_LEN_CHOICES) * 2

    print(f"Simulating: port={args.port}  baud={args.baud}  out={out_path}  "
          f"duration={duration:.0f}s  rate={PACKET_RATE}/s  seed={args.seed}",
          file=sys.stderr)
    print(f"Packet:     {HEADER_STRUCT.size}B header + csi_len*int16  "
          f"({min_pkt}-{max_pkt}B, csi_len in {CSI_LEN_CHOICES})",
          file=sys.stderr)
    print(f"Faults:     loss={args.loss_rate*100:.1f}%/pkt  "
          f"noise={args.noise_rate*100:.3f}%/byte",
          file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    stream, generated, lost = generate_stream(rng, duration, PACKET_RATE, args.loss_rate)
    raw_bytes, noise_count  = apply_noise(rng, stream.getvalue(), args.noise_rate)
    total                   = len(raw_bytes)

    # Average packet size (csi_len varies per packet)
    avg_pkt = total / generated if generated > 0 else (min_pkt + max_pkt) / 2

    bytes_saved = 0
    found_magic = False
    buf_accum   = b""
    start_time  = time.monotonic()
    last_report = start_time
    offset      = 0
    next_send   = start_time + 1.0 / PACKET_RATE

    with open(out_path, "wb") as out_f:
        while offset < total:
            # Pace delivery to real packet rate
            now = time.monotonic()
            if now < next_send:
                time.sleep(next_send - now)
            next_send += 1.0 / PACKET_RATE

            # Vary read-chunk size ±20% to simulate uneven UART read() returns
            jitter     = int(rng.uniform(-0.2, 0.2) * avg_pkt)
            chunk_size = max(1, min(int(avg_pkt) + jitter, total - offset))
            data       = raw_bytes[offset: offset + chunk_size]
            offset    += chunk_size

            if not found_magic:
                buf_accum += data
                idx = buf_accum.find(MAGIC)
                if idx != -1:
                    found_magic  = True
                    out_f.write(MAGIC)
                    bytes_saved += len(MAGIC)
                    tail         = buf_accum[idx + len(MAGIC):]
                    if tail:
                        out_f.write(tail)
                        bytes_saved += len(tail)
                    buf_accum = b""
                else:
                    if len(buf_accum) > len(MAGIC) - 1:
                        buf_accum = buf_accum[-(len(MAGIC) - 1):]
            else:
                out_f.write(data)
                bytes_saved += len(data)

            now = time.monotonic()
            if not args.quiet and now - last_report >= 1.0:
                elapsed   = now - start_time
                pkt_count = int(bytes_saved / avg_pkt)
                print(f"saved={bytes_saved} bytes | elapsed={elapsed:.1f}s "
                      f"| ~{pkt_count} packets",
                      file=sys.stderr)
                last_report = now

    if not args.quiet:
        elapsed   = time.monotonic() - start_time
        pkt_count = int(bytes_saved / avg_pkt)
        print("-" * 60, file=sys.stderr)
        print(f"Done. Wrote {bytes_saved} bytes to {out_path}", file=sys.stderr)
        print(f"  generated={generated}  dropped={lost}  "
              f"noise_bytes={noise_count}  elapsed={elapsed:.1f}s",
              file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate csi_uart_capture.py terminal output with dummy data."
    )
    parser.add_argument("port",          nargs="?", default="COM3",
                        help="Simulated serial port label (default: COM3)")
    parser.add_argument("-b", "--baud",  type=int,   default=921600)
    parser.add_argument("-o", "--out",               default="csi_sim.bin")
    parser.add_argument("--duration",    type=float, default=10.0,
                        help="Simulated capture duration in seconds (default: 10)")
    parser.add_argument("--read-size",   type=int,   default=4096,
                        help="(unused; chunk size is derived from avg packet size)")
    parser.add_argument("--loss-rate",   type=float, default=0.03,
                        help="Per-packet drop probability 0..1 (default: 0.03)")
    parser.add_argument("--noise-rate",  type=float, default=0.001,
                        help="Per-byte corruption probability 0..1 (default: 0.001)")
    parser.add_argument("--seed",        type=int,   default=42,
                        help="RNG seed for reproducible output (default: 42)")
    parser.add_argument("--quiet",       action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(simulate(parse_args()))
