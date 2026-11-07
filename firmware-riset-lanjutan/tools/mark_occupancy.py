#!/usr/bin/env python3
"""Pencatat jumlah orang per zona (A/B/C/D) secara live saat capture berjalan.

Dipakai berdampingan dengan `csi_collector.py` di terminal terpisah, persis
seperti `mark_events.py`. Bedanya: `mark_events.py` mencatat KEJADIAN SESAAT
(orang melewati sudut), sedangkan skrip ini mencatat KEADAAN (state) -- berapa
orang yang sedang berada di tiap zona, dan keadaan itu berlaku terus sampai
tombol berikutnya ditekan.

Perbedaan itu bukan detail: label counting harus berupa INTERVAL, bukan titik.
Tiap bin CSI perlu tahu "saat itu ada berapa orang di A", dan jawabannya adalah
keadaan terakhir yang tercatat sebelum bin itu -- bukan penanda terdekat.

Denah (sama dengan LOCALIZATION_RUNBOOK.md, router di TENGAH sebagai pusat):

              9 m
    A ---------------------- B        A = kiri-atas   (board 38)
    |                        |        B = kanan-atas  (board bf)
    |           R            |  7 m   C = kiri-bawah  (board d0)
    |       (router)         |        D = kanan-bawah (board 4b)
    |                        |
    C ---------------------- D

Tombol:

    a / b / c / d     TAMBAH 1 orang di zona itu
    A / B / C / D     KURANGI 1 orang (huruf besar, pakai Shift)
    1..4              set zona A..D ke nol
    z                 undo perubahan terakhir
    0                 kosongkan semua zona (semua orang keluar ruangan)
    p                 cetak keadaan sekarang tanpa mengubah apa pun
    q / Ctrl-C        selesai dan tulis file

Menekan huruf kecil dua kali menambah DUA orang -- bukan membatalkan. Untuk
mengurangi, pakai huruf besar (Shift+A). Ini disengaja: skema "tekan dua kali
untuk mengurangi" mustahil dibedakan dari "dua orang masuk berurutan", dan
salah tebak di situ merusak seluruh label sesi tanpa jejak.

Pemakaian (terminal #3, di samping kolektor):

    python tools\\mark_occupancy.py --outdir capture\\count_sesi1

    # mulai dengan orang yang sudah ada di ruangan
    python tools\\mark_occupancy.py --outdir capture\\count_sesi1 --initial A=2,B=1

Keluaran, dua file di dalam --outdir:

  occupancy_events.csv  satu baris per PENEKANAN TOMBOL (log mentah, bisa diaudit)
      host_time,t_rel,key,action,zone,A,B,C,D,total

  occupancy.csv         satu baris per INTERVAL keadaan (ini yang dipakai label)
      t_start,t_end,dur,A,B,C,D,total
      t_start/t_end = host_time absolut, jam yang SAMA dengan host_time di
      tiap record .bin kolektor -- jadi bisa langsung di-join tanpa kalibrasi.

Untuk memberi label ke CSV hasil csi_merge.py, pakai `label_occupancy.py`.
"""

import argparse
import csv
import os
import sys
import time

ZONES = ["A", "B", "C", "D"]

# Hanya untuk ditampilkan, supaya operator tidak salah tekan saat sibuk
# memperhatikan ruangan. Cocokkan dengan denah di LOCALIZATION_RUNBOOK.md.
ZONE_DESC = {
    "A": "kiri-atas   (board 38)",
    "B": "kanan-atas  (board bf)",
    "C": "kiri-bawah  (board d0)",
    "D": "kanan-bawah (board 4b)",
}

EVENT_FIELDS = ["host_time", "t_rel", "key", "action", "zone",
                "A", "B", "C", "D", "total"]
STATE_FIELDS = ["t_start", "t_end", "dur", "A", "B", "C", "D", "total"]


# --------------------------------------------------------------------------
# Pembacaan tombol tanpa Enter.
#
# Kenapa tidak input(): operator sedang mengamati ruangan, bukan layar. Menekan
# "a" lalu Enter menambah satu keystroke di saat yang justru paling sibuk, dan
# waktu yang tercatat jadi waktu Enter, bukan waktu kejadian. Selisihnya ratusan
# ms -- cukup untuk menggeser beberapa bin 100 ms ke keadaan yang salah.
# --------------------------------------------------------------------------
def make_key_reader():
    """Kembalikan fungsi baca-satu-tombol (blocking) untuk platform ini."""
    try:
        import msvcrt  # Windows
    except ImportError:
        pass
    else:
        def read_key_win():
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):   # tombol panah/fungsi: buang kode kedua
                msvcrt.getwch()
                return None
            return ch
        return read_key_win

    # POSIX: taruh terminal ke mode cbreak selama skrip berjalan.
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def read_key_posix():
        return sys.stdin.read(1)

    read_key_posix.restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return read_key_posix


def parse_initial(spec):
    """Urai '--initial A=2,B=1' menjadi dict jumlah awal per zona."""
    counts = {z: 0 for z in ZONES}
    if not spec:
        return counts
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"--initial: '{part}' bukan format ZONA=JUMLAH")
        z, _, n = part.partition("=")
        z = z.strip().upper()
        if z not in counts:
            raise SystemExit(f"--initial: zona '{z}' tidak dikenal (pakai A/B/C/D)")
        try:
            n = int(n)
        except ValueError:
            raise SystemExit(f"--initial: '{n}' bukan angka")
        if n < 0:
            raise SystemExit("--initial: jumlah tidak boleh negatif")
        counts[z] = n
    return counts


def fmt_state(counts, t_rel=None):
    body = "  ".join(f"{z}={counts[z]}" for z in ZONES)
    total = sum(counts.values())
    head = f"t+{t_rel:7.2f}s  " if t_rel is not None else ""
    return f"{head}{body}   total={total}"


def banner():
    print()
    print("  Zona:")
    for z in ZONES:
        print(f"    {z} = {ZONE_DESC[z]}")
    print()
    print("  Tombol:")
    print("    a b c d   tambah 1 orang di zona itu")
    print("    A B C D   kurangi 1 orang (Shift)")
    print("    1 2 3 4   set zona A..D ke nol")
    print("    z         undo penekanan terakhir")
    print("    0         kosongkan SEMUA zona")
    print("    p         cetak keadaan sekarang")
    print("    q         selesai")
    print()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--outdir", required=True,
                    help="folder sesi yang SAMA dengan --outdir kolektor")
    ap.add_argument("--initial", default="",
                    help="jumlah orang yang sudah ada saat mulai, mis. A=2,B=1")
    ap.add_argument("--name", default="occupancy.csv",
                    help="nama file interval keadaan (default occupancy.csv)")
    ap.add_argument("--events-name", default="occupancy_events.csv",
                    help="nama file log penekanan tombol")
    args = ap.parse_args()

    counts = parse_initial(args.initial)

    os.makedirs(args.outdir, exist_ok=True)
    path_state = os.path.join(args.outdir, args.name)
    path_events = os.path.join(args.outdir, args.events_name)

    # Satu sesi = satu folder. Menimpa label diam-diam menghasilkan angka yang
    # kelihatan wajar tapi tidak cocok dengan .bin di folder yang sama.
    for p in (path_state, path_events):
        if os.path.exists(p):
            print(f"SUDAH ADA: {p}", file=sys.stderr)
            print("Pakai --outdir baru, atau hapus file itu kalau capture diulang.",
                  file=sys.stderr)
            return 1

    read_key = make_key_reader()

    print(f"Label okupansi -> {path_state}")
    print(f"Log tombol     -> {path_events}")
    banner()

    t_start = time.time()
    events = []          # log mentah tiap penekanan
    changes = []         # (host_time, counts_snapshot) tiap kali keadaan BERUBAH
    history = []         # untuk undo: (counts_sebelum, index_event, index_change)

    # Keadaan awal dicatat sebagai perubahan pertama di t_start, supaya interval
    # pertama punya label walaupun tidak ada tombol ditekan sama sekali.
    changes.append((t_start, dict(counts)))
    print(f"  mulai   {fmt_state(counts, 0.0)}")

    def log_event(t, key, action, zone):
        events.append({
            "host_time": f"{t:.6f}",
            "t_rel": f"{t - t_start:.3f}",
            "key": key,
            "action": action,
            "zone": zone or "",
            **{z: counts[z] for z in ZONES},
            "total": sum(counts.values()),
        })

    try:
        while True:
            ch = read_key()
            if ch is None:
                continue
            # Timestamp diambil SEGERA setelah tombol terbaca, sebelum print apa
            # pun -- I/O terminal di Windows bisa memakan puluhan ms.
            t = time.time()

            if ch in ("\x03", "\x04"):    # Ctrl-C / Ctrl-D dalam mode raw
                raise KeyboardInterrupt
            if ch in ("q", "Q"):
                break

            if ch == "p":
                print(f"  (cek)   {fmt_state(counts, t - t_start)}")
                continue

            before = dict(counts)
            action = zone = None

            if ch in "abcd":
                zone = ch.upper()
                counts[zone] += 1
                action = "enter"
            elif ch in "ABCD":
                zone = ch
                if counts[zone] == 0:
                    # Menolak, bukan menyimpan -1. Jumlah negatif tidak punya arti
                    # fisik dan akan menyebar diam-diam ke seluruh label.
                    print(f"  ABAIKAN zona {zone} sudah 0, tidak bisa dikurangi")
                    continue
                counts[zone] -= 1
                action = "exit"
            elif ch in "1234":
                zone = ZONES[int(ch) - 1]
                if counts[zone] == 0:
                    print(f"  (cek)   zona {zone} memang sudah 0")
                    continue
                counts[zone] = 0
                action = "clear_zone"
            elif ch == "0":
                if sum(counts.values()) == 0:
                    print("  (cek)   ruangan memang sudah kosong")
                    continue
                for z in ZONES:
                    counts[z] = 0
                action = "clear_all"
            elif ch == "z":
                if not history:
                    print("  ABAIKAN tidak ada yang bisa di-undo")
                    continue
                prev, n_ev, n_ch = history.pop()
                counts.update(prev)
                del events[n_ev:]
                del changes[n_ch:]
                log_event(t, "z", "undo", "")
                changes.append((t, dict(counts)))
                print(f"  UNDO    {fmt_state(counts, t - t_start)}")
                continue
            else:
                continue

            history.append((before, len(events), len(changes)))
            log_event(t, ch, action, zone)
            changes.append((t, dict(counts)))

            mark = {"enter": "+1", "exit": "-1",
                    "clear_zone": "->0", "clear_all": "RESET"}[action]
            tag = f"{zone}{mark}" if zone else mark
            print(f"  {tag:<8}{fmt_state(counts, t - t_start)}")

    except KeyboardInterrupt:
        print()
    finally:
        restore = getattr(read_key, "restore", None)
        if restore:
            restore()

    t_end = time.time()

    with open(path_events, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        w.writeheader()
        w.writerows(events)

    # Gabungkan perubahan berurutan yang isinya sama. Undo bisa mengembalikan
    # keadaan ke nilai yang persis sama dengan sebelumnya; tanpa penggabungan,
    # file interval terbelah dua padahal tidak ada yang berubah -- tidak salah,
    # tapi menyesatkan saat dibaca manusia.
    merged = []
    for t, snap in changes:
        if merged and merged[-1][1] == snap:
            continue
        merged.append((t, snap))
    changes = merged

    # Ubah daftar perubahan menjadi interval tertutup [t_start, t_end).
    # Interval terakhir ditutup di waktu skrip berhenti; kalau kolektor masih
    # jalan setelah ini, bin sesudahnya memang tidak punya label -- dan itu harus
    # terlihat sebagai lubang, bukan ditambal dengan asumsi.
    rows = []
    for i, (t0, snap) in enumerate(changes):
        t1 = changes[i + 1][0] if i + 1 < len(changes) else t_end
        if t1 - t0 <= 0:
            # Dua tombol dalam satu tick jam: interval nol, tidak ada bin yang
            # bisa jatuh di dalamnya.
            continue
        rows.append({
            "t_start": f"{t0:.6f}",
            "t_end": f"{t1:.6f}",
            "dur": f"{t1 - t0:.3f}",
            **{z: snap[z] for z in ZONES},
            "total": sum(snap.values()),
        })

    with open(path_state, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=STATE_FIELDS)
        w.writeheader()
        w.writerows(rows)

    span = t_end - t_start
    print(f"Ditulis {len(events)} penekanan -> {path_events}")
    print(f"Ditulis {len(rows)} interval   -> {path_state}")
    print(f"Durasi sesi {span:.1f} s")

    if rows:
        # Ringkasan lama-waktu per jumlah total orang. Kalau satu kelas hampir
        # tidak pernah muncul, itu ketahuan di sini -- sebelum training, bukan
        # sesudah.
        by_total = {}
        for r in rows:
            by_total[r["total"]] = by_total.get(r["total"], 0.0) + float(r["dur"])
        print("Sebaran waktu per total orang:")
        for k in sorted(by_total):
            print(f"  {k} orang : {by_total[k]:7.1f} s  ({by_total[k]/span*100:5.1f}%)")
        if sum(counts.values()) != 0:
            print(f"CATATAN: sesi berakhir dengan {sum(counts.values())} orang "
                  f"masih di ruangan ({fmt_state(counts)}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
