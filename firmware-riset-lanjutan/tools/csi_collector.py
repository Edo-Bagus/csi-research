#!/usr/bin/env python3
"""Kolektor CSI multi-STA: server TCP untuk N node ESP32-C6.

Setiap ESP menyambung sebagai client dan mengirim stream biner CSI. Server ini
menerima semua koneksi secara paralel, membubuhkan timestamp kedatangan dari
jam laptop, lalu menulis satu file .bin per node.

Kenapa timestamp host: jam `rx_ctrl->timestamp` di tiap board dihitung dari boot
masing-masing board, jadi angkanya tidak bisa dibandingkan antar node. Jam laptop
adalah satu-satunya referensi bersama. Konsekuensinya timestamp mencerminkan
*kedatangan di laptop*, bukan *penerimaan di antena* -- ada jitter beberapa ms
karena buffering jaringan. Cukup untuk binning 100 ms (skema alignment (a)),
tidak cukup untuk analisis fase per-paket.

Format file keluaran (.bin), per record:

    <d>  host_time_unix       float64, jam laptop saat record selesai dibaca
    <I>  payload_len          uint32, panjang byte frame ESP di bawahnya
    ...  frame ESP apa adanya (header 50 B + len*int16)

Magic 0xDEADBEEF dari ESP dipakai untuk resync dan TIDAK ikut ditulis.

Pemakaian:
    python csi_collector.py --outdir capture/sesi1
    python csi_collector.py --outdir capture/sesi1 --duration 60
"""

import argparse
import os
import socket
import struct
import sys
import threading
import time

# Harus cocok byte-per-byte dengan csi_binary_msg_t di main/app_main.c.
# Tidak ada version field di frame, jadi perubahan di satu sisi WAJIB diikuti
# sisi lain -- kalau tidak, hasil parsing tampak masuk akal tapi isinya sampah.
#   seq       uint32   I
#   node_id   uint8    B
#   node_mac  6 bytes  6s
#   rssi      int16    h
#   rate      uint8    B
#   noise_fl  int8     b
#   fft_gain  int8     b
#   agc_gain  uint8    B
#   channel   uint8    B
#   first_wi  uint8    B
#   ap_mac    6 bytes  6s
#   timestamp uint32   I
#   uptime_us uint64   Q   (waktu capture di board)
#   sent_us   uint64   Q   (waktu kirim di board)
#   sig_len   uint16   H
#   rx_state  uint8    B
#   len       uint16   H
HEADER_STRUCT = struct.Struct("<I B 6s h B b b B B B 6s I Q Q H B H")
HEADER_SIZE = HEADER_STRUCT.size  # 50 (v2), diverifikasi cocok dengan offsetof(csi_buf) di C

MAGIC = 0xDEADBEEF
MAGIC_BYTES = struct.pack("<I", MAGIC)

# Sanity guard: len di luar rentang ini berarti stream tidak sinkron.
CSI_MAX_LEN = 1024

RECORD_PREFIX = struct.Struct("<dI")


def mac_str(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


class NodeSession(threading.Thread):
    """Satu koneksi ESP. Membaca stream, memisah frame, menulis ke file."""

    def __init__(self, conn, addr, outdir, stop_event, verbose=False):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.outdir = outdir
        self.stop_event = stop_event
        self.verbose = verbose
        self.buf = bytearray()
        self.out = None
        self.path = None
        self.node_label = None
        self.count = 0
        self.bytes_in = 0
        self.resyncs = 0
        self.last_seq = None
        self.gaps = 0
        # MAC node dikunci setelah frame pertama; dipakai sebagai jangkar
        # validasi supaya frame di offset salah tidak lolos.
        self.expect_mac = None

    def _open_output(self, node_id, node_mac):
        """File dibuka saat frame pertama tiba, karena identitas node baru
        diketahui dari isi frame -- bukan dari alamat IP koneksi."""
        mac_compact = node_mac.replace(":", "")
        self.node_label = f"node{node_id:02x}_{mac_compact}"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(self.outdir, f"{self.node_label}_{stamp}.bin")
        self.out = open(self.path, "wb")
        print(f"[{self.addr[0]}] node_id=0x{node_id:02x} mac={node_mac} -> {self.path}")

    def _resync(self):
        """Buang byte sampai magic berikutnya. Mengembalikan False kalau magic
        belum kelihatan (tunggu data lagi)."""
        idx = self.buf.find(MAGIC_BYTES, 1)
        if idx < 0:
            # Sisakan 3 byte kalau-kalau magic terpotong di batas baca.
            del self.buf[: max(0, len(self.buf) - 3)]
            return False
        del self.buf[:idx]
        self.resyncs += 1
        # seq tidak lagi bisa dipercaya berurutan setelah lompat posisi.
        self.last_seq = None
        return True

    def _plausible(self, fields):
        """Validasi header sebelum menerima frame.

        Mengecek `len` saja TIDAK cukup: pada offset yang salah, dua byte acak
        cukup sering kebetulan bernilai 512 sehingga frame sampah lolos dan
        parser terkunci di posisi salah untuk seterusnya. Identitas node adalah
        jangkar yang jauh lebih kuat -- MAC dan node_id konstan sepanjang satu
        koneksi, jadi begitu frame pertama diterima, setiap frame berikutnya
        harus cocok.
        """
        csi_len = fields[-1]
        if not (0 < csi_len <= CSI_MAX_LEN) or csi_len % 2 != 0:
            return False
        node_id, node_mac = fields[1], fields[2]
        if node_id != (node_mac[4] ^ node_mac[5]):   # sama dengan node_id_from_mac()
            return False
        if self.expect_mac is not None and node_mac != self.expect_mac:
            return False
        return True

    def _try_parse(self):
        """Ambil sebanyak mungkin frame lengkap dari self.buf."""
        while True:
            # Magic bisa muncul kapan saja di batas frame; lewati.
            while self.buf[:4] == MAGIC_BYTES:
                del self.buf[:4]

            if len(self.buf) < HEADER_SIZE:
                return

            fields = HEADER_STRUCT.unpack_from(self.buf, 0)
            csi_len = fields[-1]

            if not self._plausible(fields):
                # Stream tidak sinkron. Cari magic berikutnya dan mulai lagi
                # dari sana; jangan tebak-tebak offset.
                if not self._resync():
                    return
                continue

            total = HEADER_SIZE + csi_len * 2
            if len(self.buf) < total:
                return

            frame = bytes(self.buf[:total])
            del self.buf[:total]

            seq = fields[0]
            node_id = fields[1]
            node_mac = mac_str(fields[2])

            if self.out is None:
                self.expect_mac = fields[2]
                self._open_output(node_id, node_mac)

            # Deteksi gap: seq monotonic per node. Lompatan = paket hilang,
            # entah karena buffer ESP penuh atau reconnect.
            if self.last_seq is not None and seq > self.last_seq + 1:
                self.gaps += seq - self.last_seq - 1
            self.last_seq = seq

            # Timestamp host dibubuhkan di sini, sedekat mungkin dengan saat
            # byte terakhir frame diterima.
            host_time = time.time()
            self.out.write(RECORD_PREFIX.pack(host_time, len(frame)))
            self.out.write(frame)
            self.count += 1

            if self.verbose and self.count % 50 == 0:
                rssi = fields[3]
                print(f"  [{self.node_label}] n={self.count} seq={seq} "
                      f"rssi={rssi} len={csi_len} gaps={self.gaps}")

    def run(self):
        self.conn.settimeout(1.0)
        try:
            while not self.stop_event.is_set():
                try:
                    data = self.conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                self.bytes_in += len(data)
                self.buf.extend(data)
                self._try_parse()
        finally:
            try:
                self.conn.close()
            except OSError:
                pass
            if self.out:
                self.out.flush()
                self.out.close()
            label = self.node_label or self.addr[0]
            print(f"[{label}] selesai: {self.count} paket, "
                  f"{self.bytes_in/1024:.1f} KB, gap={self.gaps}, resync={self.resyncs}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0",
                    help="alamat bind (default semua interface)")
    ap.add_argument("--port", type=int, default=5566,
                    help="harus sama dengan COLLECTOR_PORT di firmware")
    ap.add_argument("--outdir", default="capture", help="folder output .bin")
    ap.add_argument("--duration", type=float, default=0,
                    help="berhenti otomatis setelah N detik (0 = sampai Ctrl-C)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="cetak progres tiap 50 paket per node")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((args.host, args.port))
    except OSError as exc:
        print(f"bind {args.host}:{args.port} gagal: {exc}", file=sys.stderr)
        return 1
    srv.listen(8)
    srv.settimeout(1.0)

    print(f"Kolektor siap di {args.host}:{args.port} -> {args.outdir}")
    print("Menunggu koneksi ESP... (Ctrl-C untuk berhenti)")

    stop_event = threading.Event()
    sessions = []
    start = time.monotonic()

    try:
        while not stop_event.is_set():
            if args.duration > 0 and (time.monotonic() - start) >= args.duration:
                print(f"Durasi {args.duration}s tercapai, berhenti.")
                break
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            print(f"Koneksi masuk dari {addr[0]}:{addr[1]}")
            s = NodeSession(conn, addr, args.outdir, stop_event, args.verbose)
            s.start()
            sessions.append(s)
    except KeyboardInterrupt:
        print("\nCtrl-C, menutup...")
    finally:
        stop_event.set()
        srv.close()
        for s in sessions:
            s.join(timeout=3.0)

    total = sum(s.count for s in sessions)
    print(f"\nTotal {total} paket dari {len([s for s in sessions if s.count])} node aktif.")
    for s in sessions:
        if s.count:
            print(f"  {s.node_label}: {s.count} paket, gap={s.gaps} -> {s.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
