# CSI data collection firmware: follow-up research

[Versi Indonesia](README.md)

Firmware and recording tools for collecting Wi-Fi Channel State Information (CSI) from four ESP32-C6 boards and one router. This data is used to study classroom occupancy.

This research is unfinished. Human presence was detected from the data, but the number of people and the occupancy of each zone remain unanswered. The analysis is in [analisis-riset-lanjutan](../analisis-riset-lanjutan/).

For now this folder holds everything from the original research folder and has not been sorted. The only things left out are `build/`, plus `ml_people_count/` and `ml_localization/`, which are already in the analysis folder.

## Folder contents

```text
firmware-riset-lanjutan/
├── node/                        ESP-IDF project, one binary for all boards
├── tools/
│   ├── csi_collector.py         TCP server on the laptop, one .bin file per board
│   ├── csi_merge.py             Merges .bin files into CSV
│   ├── simulate_node.py         Fake board for testing without hardware
│   ├── mark_occupancy.py        Records people per zone while capturing
│   ├── label_occupancy.py       Attaches labels to the CSV
│   ├── mark_events.py           Records time markers while capturing
│   ├── localize_baseline.py     Argmax rule for localization
│   └── legacy_uart/             UART-era scripts, unused
├── capture/                     All recordings, about 1.5 GB
├── backup/                      Firmware v1 snapshot, unused
└── docs/                        Original notes, runbooks, and two plots
```

### What differs from the source

| File | Change |
|---|---|
| `node/main/app_main.c` | 8 lines: 22, 60, 61, 66–68, 70, 74 |
| `node/main/Kconfig.projbuild` | New file for the SSID, password, and collector address |
| `tools/simulate_node.py` | Lines 33 and 58 use a fake MAC |
| `backup/v1_tcp_batched_20260909/simulate_node.py` | Same as above |
| `backup/v1_tcp_batched_20260909/app_main.c` | Password, SSID, and laptop identity masked |
| `node/main/app_main_rssi_log.c.bak` | Password and SSID masked |
| `docs/` | SSID, laptop address, and MACs masked in 4 documents |

All other files were copied without changes. `build/` is not included because the password is compiled into it.

## How it works

```text
ESP #1 ──┐
ESP #2 ──┤
ESP #3 ──┼── Wi-Fi/TCP ──> Router ──> Laptop (csi_collector.py)
ESP #4 ──┘                            One .bin file per board
```

1. Each board connects to the router, then pings the gateway every 100 ms.
2. The board captures CSI from router frames. The transmitter is the router, not a second ESP.
3. The firmware only accepts frames from the router BSSID with `sig_len` 114.
4. Each packet is sent over TCP right away. Every 1 second the board inserts the magic `0xDEADBEEF`.
5. `csi_collector.py` adds the laptop time and writes one `.bin` file per board.
6. `csi_merge.py` aligns the boards using 100 ms time bins.

`node_id` is the XOR of the last two MAC bytes, so one binary serves all boards. The four boards in this research have `node_id` `38`, `4b`, `bf`, and `d0`.

No data cable is used while recording. USB is only for flashing and power.

## Requirements

### Hardware

| Item | Quantity | Notes |
|---|---|---|
| ESP32-C6 | 4 | All use the same binary |
| ASUS RT-AX53U router | 1 | Transmitter, no WAN |
| Laptop | 1 | Runs the collector |
| USB power source | 4 | Power bank or charger |

### Software

- ESP-IDF 5.5.2
- Python 3
- numpy and matplotlib, only for `localize_baseline.py`

The other recording tools use only the Python standard library. The `esp_csi_gain_ctrl` component version is locked in `dependencies.lock`.

## Radio configuration

| Parameter | Value |
|---|---|
| Target | ESP32-C6 |
| Channel, bandwidth | 11 (2.4 GHz), 20 MHz |
| Protocol | IEEE 802.11ax |
| CSI mode | HE SU, `dcm`, `beamformed`, `he_stbc` 2, 256 subcarriers |
| Trigger | Ping to the gateway every 100 ms, 32 data bytes |
| Filter | Source equals BSSID, `sig_len` 114 |
| Gain | AGC runs free, values stored per packet |
| Power save | Off |
| Data path | TCP port 5566, Nagle off |

## Build and flash

Activate the ESP-IDF environment first.

```powershell
$env:PATH = "$env:USERPROFILE\.espressif\tools\idf-python\3.11.2;" + $env:PATH
. C:\esp\v5.5.2\esp-idf\export.ps1
```

Run the following commands in the `node` folder.

```bash
idf.py set-target esp32c6
```

```bash
idf.py menuconfig
```

Open the `CSI riset lanjutan` menu, then fill in the router SSID, Wi-Fi password, and laptop IP address. If the values are empty, the build still succeeds but the board will not connect.

```bash
idf.py build
```

Replace `COM5` with the board port. The same binary is flashed to all four boards.

```bash
idf.py -p COM5 flash monitor
```

The values you enter are stored in `node/sdkconfig` and `node/build/`. Both are in `.gitignore`, and neither should be shared.

This project was build-tested from a clean state on ESP-IDF 5.5.2. This build has not been re-tested on hardware.

### Checking a board

A healthy board monitor prints:

```text
Node MAC ... -> node_id 0x38
STA connected, BSSID ..., channel 11
Got IP ...
Tersambung ke kolektor ...:5566
node=38 rx=52 sent=52 drop=0 filt=... max_len=512 oversize=0 link=up
```

| Field | Must be | If not |
|---|---|---|
| `max_len` | 512 | Bandwidth or protocol is not HE20 |
| `link` | `up` | The board cannot reach the laptop |
| `drop` | 0 or small | The collector is not keeping up |
| `filt` | Rises slowly | Normal, these are discarded frames with another `sig_len` |

## Setting up the network

1. Set the router to channel 11, 2.4 GHz, with 802.11ax enabled.
2. Connect the laptop to that router's 2.4 GHz network.
3. Lock the laptop address with a DHCP reservation on the router.
4. Check that the laptop address matches the value in menuconfig. If it differs, the boards must be flashed again.

```bash
ipconfig
```

5. Allow the collector port in Windows Firewall. Run this once as Administrator.

```powershell
New-NetFirewallRule -DisplayName "CSI Collector 5566" -Direction Inbound -LocalPort 5566 -Protocol TCP -Action Allow
```

The router has no WAN, so the laptop has no internet while recording.

## Placing the devices

The router sits in the middle of the room, with one board in each corner at a uniform height. The router must not shift until all sessions are done, because sessions before and after a shift are no longer comparable.

Data was collected in two different classrooms. Room 1 measures 9 × 7 m, and the size of room 2 was not recorded.

```text
              9 m
    A ---------------------- B
    |                        |
    |           R            |  7 m
    |       (router)         |
    |                        |
    C ---------------------- D
```

| Zone | Position | Room 1 (`count_s*`) | Room 2 (`count_2_*`) |
|---|---|---|---|
| A | Top left | `d0` | `d0` |
| B | Top right | `bf` | `bf` |
| C | Bottom left | `38` | `4b` |
| D | Bottom right | `4b` | `38` |

The `loc_*` recordings used a different layout: `38` top left, `bf` top right, `d0` bottom left, and `4b` bottom right.

Record the layout in the session notes whenever you start in a new room. `.bin` frames do not store the layout, and the data cannot settle it if the notes are wrong.

Mark the zone boundaries on the floor with tape. Each board measures the channel from the router to that board, so a zone is a sector of direction from the router, not a sharp box.

## Recording steps

### Each session

One session uses one folder. `csi_merge.py` reads every `.bin` in that folder as one recording.

1. Run the collector first, and wait until `Kolektor siap` appears.

```bash
python tools/csi_collector.py --outdir capture/session_name --duration 360 -v
```

2. Power on all four boards together. Wait until all four appear in the collector.
3. In a second terminal, run the label recorder. `--outdir` must match the collector.

```bash
python tools/mark_occupancy.py --outdir capture/session_name
```

If the room is already occupied at the start, add for example `--initial A=2,B=1`.

| Key | Action |
|---|---|
| `a` `b` `c` `d` | Add 1 person to that zone |
| `A` `B` `C` `D` | Remove 1 person |
| `1` `2` `3` `4` | Set zone A–D to zero |
| `0` | Empty all zones |
| `z` | Undo the last key |
| `p` | Print the current state |
| `q` | Finish and write the files |

4. Stop the collector first, then press `q` in the label recorder. In the other order, the last bins have no label.
5. Check the result before moving to the next session.

### During a real class

The `count_*` data was recorded during lectures, so the subjects are students who cannot be directed. What can be done without directing anyone:

- Record without a break across the end of a class, from 10 minutes before it ends until 10 minutes after the room is empty.
- Record the empty room at different hours and days, 5 minutes each.
- Record classes of different sizes.

### Localization

There are three recordings in separate folders.

| Folder | Contents | Duration |
|---|---|---|
| `capture/loc_baseline` | Empty room | 2 minutes |
| `capture/loc_static` | Standing 30 seconds at each path corner | 2.5 minutes |
| `capture/loc_walk` | Walking in a loop for 8 laps | 5.5 minutes |

The walking order is `4b`, `bf`, `38`, `d0`, at a radius of 2–2.5 m from the router. For `loc_walk`, run the marker recorder and press Enter each time you pass a corner.

```bash
python tools/mark_events.py --outdir capture/loc_walk
```

The full procedure is in `docs/LOCALIZATION_RUNBOOK.md`.

## Checking a recording

```bash
python tools/csi_merge.py capture/session_name --stats-only --bin-ms 100
```

| What to look at | Expected value |
|---|---|
| Nodes | 4 |
| Rate per board | About 35–45 packets per second |
| Bins with all nodes | Above 90% |
| `hilang` (lost packets) | Small |

To produce a labeled CSV:

```bash
python tools/csi_merge.py capture/session_name -o session_name.csv --bin-ms 100
```

```bash
python tools/label_occupancy.py session_name.csv --occupancy capture/session_name/occupancy.csv -o session_name_labeled.csv
```

### Troubleshooting

| Symptom | Likely cause | What to check |
|---|---|---|
| Repeated `connect() ... gagal` | Laptop address differs, or the collector is not running | `ipconfig`, the collector terminal |
| `link=down` but `rx` rises | CSI arrives, TCP is not connected | Firewall and laptop address |
| `rx=0` stays there | No CSI | Router must be on channel 11 with 802.11ax enabled |
| `max_len` is not 512 | Bandwidth is not HE20 | Router settings |
| Board does not join Wi-Fi | Wrong SSID or password, or a 5 GHz network | Values in menuconfig |
| Rate of about 10 packets per second | Boards are not on at the same time | Power all four on together |
| 0% of bins hold all nodes | Board on-times do not overlap | Repeat the session |

## Testing without hardware

Run the collector in one terminal.

```bash
python tools/csi_collector.py --host 127.0.0.1 --outdir sim_test --duration 15
```

Run the fake boards in another terminal.

```bash
python tools/simulate_node.py --nodes 4 --rate 40 --duration 10
```

Then check with `csi_merge.py`. The `--drop-rate`, `--split-writes`, and `--garbage` options test collector robustness. This path has been tested: 960 packets sent and 960 stored with no gaps.

## `.bin` file format

The file is a series of records, little-endian and packed. The board's magic `0xDEADBEEF` is not stored.

| Part | Type | Description |
|---|---|---|
| `host_time` | `float64` | Laptop time when the frame finished reading |
| `payload_len` | `uint32` | Frame length |
| Frame | `payload_len` bytes | 50-byte header, then CSI data |

Frame header:

| Offset | Type | Field | Description |
|---|---|---|---|
| 0 | `uint32` | `seq` | Local board counter |
| 4 | `uint8` | `node_id` | XOR of the last two MAC bytes |
| 5 | `uint8[6]` | `node_mac` | Board MAC |
| 11 | `int16` | `rssi` | RSSI (dBm) |
| 13 | `uint8` | `rate` | Rate value from the driver |
| 14 | `int8` | `noise_floor` | Noise floor |
| 15 | `int8` | `fft_gain` | FFT gain |
| 16 | `uint8` | `agc_gain` | AGC gain |
| 17 | `uint8` | `channel` | Wi-Fi channel |
| 18 | `uint8` | `first_word_invalid` | Flag from the driver |
| 19 | `uint8[6]` | `ap_mac` | Router BSSID |
| 25 | `uint32` | `timestamp` | Receiver timestamp (µs), local board clock |
| 29 | `uint64` | `uptime_us` | Board clock at capture |
| 37 | `uint64` | `sent_us` | Board clock when entering the socket |
| 45 | `uint16` | `sig_len` | Packet length, always 114 |
| 47 | `uint8` | `rx_state` | Reception status |
| 48 | `uint16` | `len` | Number of CSI values, always 512 |
| 50 | `int16[len]` | `csi` | CSI data |

Python struct format for the header:

```python
HEADER = struct.Struct("<I B 6s h B b b B B B 6s I Q Q H B H")
```

Frames have no version field. If the struct in the firmware changes, `csi_collector.py`, `csi_merge.py`, and `simulate_node.py` must change with it. A mismatch produces data that parses but is wrong, not an error.

## Things to know

- **Packet rate follows the number of boards.** Each board pings only 10 times per second, but its rate is about 10 × the number of boards running.

| Condition | Boards running | Rate per board |
|---|---|---|
| `sesi4` and 4 extra files in `count_s09`, boards powered in turn | 1 | 9.9–10.2 Hz |
| `sesi2` | 2 | 20.9–21.5 Hz |
| `count_s01` after `bf` died at second 11 | 3 | 26.5–35.5 Hz |
| `sesi3`, `count_s05`, `count_2_4` | 4 | 36.0–43.5 Hz |

- **Boards capture the same physical frames.** In 5 sessions, 84–99.9% of packets have a counterpart on another board within ±100 µs by `timestamp`. A control with the offset shifted by 7.3 ms gets only 0.4–1.3%. The frame's destination address is not stored, so the idea that these frames are ping replies for other boards is unproven. The firmware does not store `dmac` and `rx_seq`, which could confirm it.
- **The reference for lost packets is `hilang` from `csi_merge.py`.** The collector's `gap` does not count packets lost during a resync.
- **Active subcarriers.** Indices 0–2, 64, 126–130, and 192 are always zero. Another 242 indices are nonzero in nearly all packets, and indices 252–255 are nonzero in only 16–58% of packets. This layout differs from the thesis data, so the thesis mask must not be used.
- **CSI values are raw.** The firmware does not compensate for gain, and AGC runs free.
- **Not everything in `capture/` is a main session.** The main sessions are `count_s01`–`count_s10`, `count_2_1`–`count_2_9`, and `loc_*`. The rest appear to be trials. Two files in `sesi1` use the old 42-byte header, so the tools here cannot read them. `count_s09` has 4 extra small files, and `count_s01_kosong` holds labels only.
- **Recordings include device identity.** File names and frame contents include board MACs and the router BSSID. Keep this in mind if the data is published.
- **`capture/` here is not a backup.** This folder is on the same disk as its source.

### Outdated comments

The comments and notes below were deliberately left unchanged.

| Location | Says | Actually |
|---|---|---|
| `node/main/app_main.c` line 77 | About 10 packets per second | About 40 with 4 boards |
| `node/main/app_main.c` line 118 | About 13 packets per second | About 40 with 4 boards |
| `node/main/app_main.c` lines 315–317 | Two boards observe different packets | Boards capture the same frames |
| `tools/csi_merge.py` lines 8–11 | Each board's packets differ | Boards capture the same frames |
| `tools/mark_occupancy.py` | Screen shows A = `38`, C = `d0` | Matches neither room 1 nor room 2. Labels are unaffected |
| `node/sdkconfig.defaults` | RSSI text log mode and `printf` from the callback | The firmware now streams over TCP |
| `docs/KNOWLEDGE.md` §0.3 | 42-byte header | 50-byte header |
| `docs/KNOWLEDGE.md` §2.2, §2.4, §3, §4, §6, §8, §10 | RSSI log mode, 1000 ms ping | Legacy from before v2 |
| `docs/KNOWLEDGE.md` §0.4 | Each board's packets differ | Boards capture the same frames |
| `docs/COUNTING_RUNBOOK.md` | The router replies more than once per ping | A board alone gets 10 Hz |
| `docs/COUNTING_RUNBOOK.md` line 42 | Layout in `ml_people_count/loader.py` | Now in `src/csi_occupancy/datasets.py` |

## Dataset

The Phase 3 recordings have not been published.

## Code origin

This firmware was developed from `CSI_recv_v2`, which came from the `get-started` example in Espressif's [esp-csi](https://github.com/espressif/esp-csi), licensed under Apache-2.0. This copy was taken from `esp/RISET_CSI_2/` in `CSI-PeopleCounting`.
