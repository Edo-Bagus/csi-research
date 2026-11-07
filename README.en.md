# Wi-Fi CSI research on ESP32-C6

[Versi Indonesia](README.md)

Firmware, recording tools, analysis code, and results for estimating people count and room occupancy with Wi-Fi 802.11ax Channel State Information (CSI) on ESP32-C6.

The research has three phases. Phases 1 and 2 share the same data and firmware. Phase 3 uses a new system and was not finished.

## Repository contents

| Folder | Contents | Phase | Status |
|---|---|---|---|
| [firmware-skripsi-conference](firmware-skripsi-conference/) | Firmware for two ESP32-C6 boards and UART recording tools | 1, 2 | Complete. Clean build tested, not re-tested on hardware |
| [training-skripsi-conference](training-skripsi-conference/) | Training code and final results | 1, 2 | Partial. Feature extraction and training cannot run yet |
| [firmware-riset-lanjutan](firmware-riset-lanjutan/) | Firmware for four ESP32-C6 boards, TCP recording tools, recordings | 3 | Temporary, not sorted yet. Clean build tested, not re-tested on hardware |
| [analisis-riset-lanjutan](analisis-riset-lanjutan/) | Occupancy analysis, localization, and labels | 3 | Complete. Results were re-run successfully, but `.bin` files are required |

Each folder has Indonesian and English READMEs, and its own `.gitignore`.

## Three phases

| | Phase 1: Thesis | Phase 2: Conference paper | Phase 3: Follow-up research |
|---|---|---|---|
| Hardware | 2 ESP32-C6-DevKitC-1 | Same as phase 1 | 4 ESP32-C6 and an ASUS RT-AX53U router |
| Packet source | ESP-NOW broadcast from the transmitter | Same as phase 1 | Ping to the gateway, CSI from router frames |
| Data path | UART (v2) to a PC through a USB-TTL adapter | Same as phase 1 | TCP to a laptop, no data cable |
| Location | 7 × 9 m room, zones A and B | Same as phase 1 | Two different classrooms |
| Subjects | The researcher and 5 volunteers | Same as phase 1 | Students attending a lecture |
| Question | How many people, 0 to 6 | Same, plus recording-level significance tests | Can real classroom occupancy be detected without directing people |

Phases 1 and 2 have manuscripts:

- Thesis: *Studi Komparatif Model Machine Learning untuk Penghitungan Jumlah Orang dalam Ruangan Berbasis Channel State Information (CSI) Wi-Fi 802.11ax pada Perangkat ESP32-C6*.
- Paper: *Comparative Study of Machine Learning Models for Indoor People Counting Based on Wi-Fi 802.11ax Channel State Information (CSI) on ESP32-C6*.

## Flow

```text
Phases 1, 2   firmware-skripsi-conference ──> Zenodo dataset ──> training-skripsi-conference

Phase 3       firmware-riset-lanjutan ──> capture/ ──> analisis-riset-lanjutan
```

## Results at a glance

### Phases 1 and 2

The values below are the mean and standard deviation over 4 outer folds.

| Task | Best model | Result |
|---|---|---|
| Classification, magnitude features | 1D CNN | Accuracy 0.936 ± 0.030, F1-macro 0.944 ± 0.030 |
| Regression | CNN-LSTM | MAE 0.243 ± 0.062, R² 0.934 ± 0.031 |

Each label comes from only one group of recording files, and radio conditions differ per label. So these figures do not yet separate the effect of the number of people from the effect of the recording session.

### Phase 3

| Question | Result |
|---|---|
| Empty or occupied | Temporal coherence separates 19 sessions with no overlap, with only 2 empty sessions |
| How many people | Unanswered |
| Which zone is occupied | Unanswered |
| Which quadrant one walking person is in | 89.9% on one session with one person |

## Data

| Data | Location | Status |
|---|---|---|
| Phases 1 and 2: 58 recordings | [10.5281/zenodo.21467952](https://doi.org/10.5281/zenodo.21467952) | Published, CC BY 4.0 |
| Phase 3: 19 class sessions, 3 localization recordings, and trial sessions | `firmware-riset-lanjutan/capture/` | Not published |

The Phase 3 `.bin` files total about 1.5 GB and are in `.gitignore`, so they exist only on the local disk. The label CSVs are kept. These recordings include board MACs and the router BSSID, so they need review before publication.

## Where to start

| Goal | Folder |
|---|---|
| Repeat the thesis recordings | [firmware-skripsi-conference](firmware-skripsi-conference/) |
| See the thesis and paper results | [training-skripsi-conference](training-skripsi-conference/) |
| Record with four boards | [firmware-riset-lanjutan](firmware-riset-lanjutan/) |
| Run the occupancy or localization analysis | [analisis-riset-lanjutan](analisis-riset-lanjutan/) |

All folders share ESP-IDF 5.5.2 for firmware and Python 3 for recording tools and analysis. Each folder's README lists its Python packages.

## Differences between phases

The two systems use different data formats, so tools and subcarrier masks must not be swapped. Frames also have no version field, so wrongly parsed data looks plausible instead of raising an error.

| | Phases 1 and 2 | Phase 3 |
|---|---|---|
| Transmitter | A second ESP32-C6 | Router |
| Frame header | 28 bytes | 50 bytes |
| `sig_len` | 47 | 114 |
| Zero subcarriers | 0–5, 127–129, 251–255 | 0–2, 64, 126–130, 192 |
| Board identity | Fixed in firmware | From the MAC at runtime |
| Reader tool | `csi_bin_to_csv.py` | `csi_merge.py` |

In Phase 3, subcarriers 252–255 are nonzero in only some packets.

## Credentials

There are no Wi-Fi passwords in this repository. The Phase 3 firmware reads the SSID, password, and collector address from `idf.py menuconfig`. Once filled in, the values are stored in `sdkconfig` and `build/`, so neither location should be shared.

## License

This repository has no license file yet. The firmware was developed from Espressif's [esp-csi](https://github.com/espressif/esp-csi), licensed under Apache-2.0. The Zenodo dataset is licensed under CC BY 4.0.

## Code origin

All folders were assembled from copies of the `CSI-PeopleCounting` and [CSI-ML](https://github.com/Edo-Bagus/CSI-ML) repositories. Changes from the sources are recorded in each folder's README.
