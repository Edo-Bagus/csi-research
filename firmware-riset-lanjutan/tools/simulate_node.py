#!/usr/bin/env python3
"""Simulator node ESP32-C6: client TCP palsu untuk menguji csi_collector.py.

Menirukan persis apa yang dikirim firmware (frame biner + magic berkala), jadi
seluruh jalur host bisa diuji tanpa hardware dan tanpa router. Dipakai di Phase 1
saat board belum terpasang.

Fault model opsional untuk memastikan kolektor tahan gangguan nyata:
  --drop-rate     paket sengaja dilewati -> seq melompat, kolektor harus
                  melaporkannya sebagai gap
  --split-writes  frame dipotong di tengah lalu dikirim terpisah -> menguji
                  penanganan TCP yang datang tidak utuh
  --garbage       menyisipkan byte sampah -> menguji resync lewat magic

Pemakaian:
    python simulate_node.py --nodes 2 --rate 10 --duration 10
    python simulate_node.py --nodes 2 --drop-rate 0.05 --garbage
"""

import argparse
import math
import random
import socket
import struct
import sys
import threading
import time

HEADER_STRUCT = struct.Struct("<I B 6s h B b b B B B 6s I Q Q H B H")
MAGIC_BYTES = struct.pack("<I", 0xDEADBEEF)

CSI_LEN = 512          # nilai normal HE20: 512 int16 = 256 subcarrier
AP_MAC = bytes.fromhex("020000000001")   # BSSID tiruan


def make_csi(n_sub, t, node_seed):
    """CSI sintetis: amplitudo bervariasi per subcarrier + drift lambat.

    Bukan model kanal yang realistis -- tujuannya hanya menghasilkan angka yang
    bervariasi dan deterministik supaya kebenaran parsing bisa dicek.
    """
    vals = []
    for k in range(n_sub):
        amp = 20 + 10 * math.sin(k / 8.0 + node_seed)
        phase = (k * 0.3) + t * 0.5 + node_seed
        vals.append(int(amp * math.cos(phase)))
        vals.append(int(amp * math.sin(phase)))
    return vals


class FakeNode(threading.Thread):
    def __init__(self, idx, args):
        super().__init__(daemon=True)
        self.idx = idx
        self.args = args
        # MAC unik per node; node_id = XOR dua byte terakhir, sama seperti
        # node_id_from_mac() di firmware.
        self.mac = bytes.fromhex("0200000000") + bytes([0x10 + idx])
        self.node_id = self.mac[4] ^ self.mac[5]
        self.sent = 0
        self.skipped = 0
        self.err = None

    def run(self):
        try:
            sock = socket.create_connection((self.args.host, self.args.port), timeout=5)
        except OSError as exc:
            self.err = f"connect gagal: {exc}"
            return

        rng = random.Random(self.args.seed + self.idx)
        print(f"node{self.node_id:02x} mac={self.mac.hex(':')} tersambung")

        try:
            sock.sendall(MAGIC_BYTES)
            interval = 1.0 / self.args.rate
            start = time.monotonic()
            last_magic = start
            seq = 0
            next_send = start

            while True:
                now = time.monotonic()
                if self.args.duration > 0 and (now - start) >= self.args.duration:
                    break
                if now < next_send:
                    time.sleep(min(next_send - now, 0.05))
                    continue
                next_send += interval

                seq += 1
                # Paket di-drop SETELAH seq dinaikkan, meniru paket yang hilang
                # di ESP: seq melompat, persis seperti buffer penuh.
                if rng.random() < self.args.drop_rate:
                    self.skipped += 1
                    continue

                t = now - start
                csi = make_csi(CSI_LEN // 2, t, self.idx)
                header = HEADER_STRUCT.pack(
                    seq,                              # seq
                    self.node_id,                     # node_id
                    self.mac,                         # node_mac
                    -40 - self.idx * 5 + rng.randint(-2, 2),  # rssi
                    11,                               # rate
                    -97,                              # noise_floor
                    -36,                              # fft_gain
                    42,                               # agc_gain
                    11,                               # channel
                    0,                                # first_word_invalid
                    AP_MAC,                           # ap_mac
                    int(t * 1e6) & 0xFFFFFFFF,        # timestamp (jam lokal board)
                    int(t * 1e6),                     # uptime_us (capture)
                    int(t * 1e6) + 500,               # sent_us (kirim, +0.5ms)
                    114,                              # sig_len
                    0,                                # rx_state
                    CSI_LEN,                          # len
                )
                frame = header + struct.pack(f"<{CSI_LEN}h", *csi)

                if self.args.garbage and rng.random() < 0.01:
                    # Sampah di batas frame: kolektor harus resync lewat magic
                    # berikutnya, bukan menulis frame rusak.
                    sock.sendall(bytes(rng.randbytes(rng.randint(1, 20))))

                if self.args.split_writes and rng.random() < 0.3:
                    cut = rng.randint(1, len(frame) - 1)
                    sock.sendall(frame[:cut])
                    time.sleep(0.001)
                    sock.sendall(frame[cut:])
                else:
                    sock.sendall(frame)
                self.sent += 1

                if (now - last_magic) >= 1.0:
                    sock.sendall(MAGIC_BYTES)
                    last_magic = now
        except OSError as exc:
            self.err = f"kirim gagal: {exc}"
        finally:
            try:
                sock.close()
            except OSError:
                pass
            print(f"node{self.node_id:02x} selesai: terkirim={self.sent} dilewati={self.skipped}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5566)
    ap.add_argument("--nodes", type=int, default=2, help="jumlah node simulasi")
    ap.add_argument("--rate", type=float, default=10.0, help="paket/detik per node")
    ap.add_argument("--duration", type=float, default=10.0, help="detik (0 = tak terbatas)")
    ap.add_argument("--drop-rate", type=float, default=0.0,
                    help="peluang paket dilewati, meniru buffer ESP penuh")
    ap.add_argument("--split-writes", action="store_true",
                    help="potong frame di tengah untuk menguji reassembly TCP")
    ap.add_argument("--garbage", action="store_true",
                    help="sisipkan byte sampah untuk menguji resync")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    nodes = [FakeNode(i, args) for i in range(args.nodes)]
    for n in nodes:
        n.start()
        time.sleep(0.2)   # jangan connect serentak, biar log terbaca
    for n in nodes:
        n.join()

    total = sum(n.sent for n in nodes)
    print(f"\nTotal terkirim {total} paket dari {args.nodes} node.")
    for n in nodes:
        if n.err:
            print(f"  node{n.node_id:02x} ERROR: {n.err}")
    return 1 if any(n.err for n in nodes) else 0


if __name__ == "__main__":
    sys.exit(main())
