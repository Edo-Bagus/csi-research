#!/usr/bin/env python3
import argparse
import sys
import time

MAGIC = b"\xef\xbe\xad\xde"  # 0xDEADBEEF little-endian


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture CSI binary stream from UART.")
    parser.add_argument("port", help="Serial port (e.g. COM3, /dev/ttyUSB0)")
    parser.add_argument("-b", "--baud", type=int, default=921600, help="Baud rate")
    parser.add_argument("-o", "--out", default="csi_uart.bin", help="Output .bin file path")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds (0 = no limit)")
    parser.add_argument("--max-bytes", type=int, default=0, help="Stop after N bytes (0 = no limit)")
    parser.add_argument("--read-size", type=int, default=4096, help="Serial read chunk size")
    parser.add_argument("--no-sync", action="store_true", help="Write immediately without searching for magic")
    parser.add_argument("--quiet", action="store_true", help="Disable progress output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        import serial  # type: ignore
    except Exception:
        print("Missing dependency: pyserial. Install with: pip install pyserial", file=sys.stderr)
        return 1

    start_time = time.monotonic()
    last_report = start_time
    bytes_saved = 0
    found_magic = args.no_sync
    buffer = b""

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except Exception as exc:
        print(f"Failed to open serial port: {exc}", file=sys.stderr)
        return 1

    try:
        with open(args.out, "wb") as out:
            while True:
                data = ser.read(args.read_size)
                now = time.monotonic()

                if not found_magic:
                    if data:
                        buffer += data
                        idx = buffer.find(MAGIC)
                        if idx != -1:
                            found_magic = True
                            out.write(MAGIC)
                            bytes_saved += len(MAGIC)
                            tail = buffer[idx + len(MAGIC):]
                            if tail:
                                out.write(tail)
                                bytes_saved += len(tail)
                            buffer = b""
                        else:
                            if len(buffer) > len(MAGIC) - 1:
                                buffer = buffer[-(len(MAGIC) - 1):]
                else:
                    if data:
                        out.write(data)
                        bytes_saved += len(data)

                if not args.quiet and now - last_report >= 1.0:
                    elapsed = now - start_time
                    print(f"saved={bytes_saved} bytes | elapsed={elapsed:.1f}s", file=sys.stderr)
                    last_report = now

                if args.duration > 0 and (now - start_time) >= args.duration:
                    break

                if args.max_bytes > 0 and bytes_saved >= args.max_bytes:
                    break

    except KeyboardInterrupt:
        pass
    finally:
        try:
            ser.close()
        except Exception:
            pass

    if not args.quiet:
        print(f"Done. Wrote {bytes_saved} bytes to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
