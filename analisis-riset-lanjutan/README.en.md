# Follow-up research analysis: classroom occupancy and localization

[Versi Indonesia](README.md)

Code and results for analyzing Wi-Fi Channel State Information (CSI) from four ESP32-C6 boards and one router. This folder holds two analyses: occupancy detection in two classrooms, and quadrant localization on one session.

This research is unfinished. Human presence was detected, but the number of people and the occupancy of each zone remain unanswered.

## Status

| Question | Result | Limit |
|---|---|---|
| Empty or occupied | Temporal coherence separates 19 sessions with no overlap | Only 2 empty sessions, one per room |
| How many people | Unanswered | Coherence is unrelated to the number of people |
| Which zone is occupied | Unanswered | The real layout does not beat other permutations |
| Which quadrant one walking person is in | 89.9%, leave-one-lap-out | One person, one session, 8 laps |

| Part | Runnable |
|---|---|
| Tests without raw data | Yes, right away |
| Full tests, three analyses, two notebooks | Yes, after the `.bin` files are restored |

## Folder contents

```text
analisis-riset-lanjutan/
├── tools/
│   ├── csi_merge.py               .bin frame reader, used by both analyses
│   └── localize_baseline.py       Hand-written argmax rule, localization baseline
├── ml_people_count/
│   ├── src/csi_occupancy/         Occupancy analysis package
│   ├── tests/                     25 tests
│   ├── notebooks/                 Room 1 notebook, stored without outputs
│   ├── results/                   Result figures and tables
│   ├── data/raw/                  Occupancy labels per session, no .bin files
│   └── README.md                  Original notes
└── ml_localization/
    ├── features.py                Feature extraction
    ├── localization_ml.ipynb      Main notebook, stored with outputs
    ├── figures/                   Result figures
    ├── data/loc_walk/markers.csv  Lap markers
    └── README.md                  Original notes
```

All code, results, and labels were copied without changes. `static.png` and `walk.png` were moved from the root of the original research folder to `ml_localization/figures/`. The `.bin` files, feature caches, and trained models are not included.

`tools/` must stay next to `ml_people_count/` and `ml_localization/`, because both analyses import `read_bin` from `../tools/csi_merge.py`.

## Flow

```text
.bin per board ──> read_bin ──┬──> csi_occupancy: windows, labels, coherence, null controls
                              └──> features.py: 500 ms windows, normalization, quadrant model
```

## Data

| Dataset | Date | Location | Sessions | `.bin` files | Empty session |
|---|---|---|---|---|---|
| `data-14-9` | 2026-09-14 | Classroom 1, class of 7–16 people | 10 | 39 | `count_s10` |
| `data-15-9` | 2026-09-15 | Classroom 2, class of 45–72 people | 9 | 36 | `count_2_9` |
| `loc_baseline`, `loc_static`, `loc_walk` | 2026-09-09 | Not recorded | 3 | 12 | `loc_baseline` |

The first two datasets were recorded during real classes, so the subjects are students attending a lecture. Protocols that assume control over people do not apply here.

### Zone layout

The router sits in the middle of the room, with a board in each corner.

| Zone | Position | Room 1 | Room 2 |
|---|---|---|---|
| A | Top left | `d0` | `d0` |
| B | Top right | `bf` | `bf` |
| C | Bottom left | `38` | `4b` |
| D | Bottom right | `4b` | `38` |

The `loc_*` recordings used a different layout: `38` top left, `bf` top right, `d0` bottom left, and `4b` bottom right.

`.bin` frames do not store the layout, and the data cannot settle it if the notes are wrong. The room layouts are in `zone_board` in `src/csi_occupancy/datasets.py`.

### Restoring the `.bin` files

The raw Phase 3 data has not been published. The `.bin` files are in the original research folder, `esp/RISET_CSI_2/`, about 1.5 GB in total. Copy them to the same paths here:

```text
ml_people_count/data/raw/<dataset>/<session>/*.bin
ml_localization/data/loc_baseline/*.bin
ml_localization/data/loc_static/*.bin
ml_localization/data/loc_walk/*.bin
```

Copy from `ml_people_count/data/raw/` and `ml_localization/data/` in the original folder, not from `capture/`. `capture/count_s09` has 4 extra small files, and `load_session` keeps only one file per board, so those files would overwrite the main recording.

File names and frame contents include board MAC addresses and the router BSSID. Keep this in mind if the data is ever published.

## Requirements

- Python 3.12.2
- The packages in `ml_people_count/requirements.txt`, plus pytest
- For localization: xgboost and Jupyter

```bash
pip install -r ml_people_count/requirements.txt pytest xgboost==3.2.0 jupyter
```

## Running

### Occupancy

Run from the `ml_people_count` folder, and point Python at the package in this folder.

```powershell
cd ml_people_count
$env:PYTHONPATH = "src"
```

Check that the printed path is inside this folder.

```bash
python -c "import csi_occupancy; print(csi_occupancy.__file__)"
```

On the research computer, `csi_occupancy` is still installed from the original folder. Without `PYTHONPATH`, the commands below use the original code and write results there.

Without raw data:

```bash
python -m pytest tests -m "not needs_data"
```

Expected result: 17 tests pass. Without this filter, the 8 tests that need data fail instead of being skipped.

With raw data:

```bash
python -m pytest tests
```

```bash
python -m csi_occupancy.eda_windows
```

```bash
python -m csi_occupancy.session_level
```

```bash
python -m csi_occupancy.coherence
```

The first run takes about 5 minutes. The feature cache goes to `data/processed/`, and result tables go to `results/tables/`.

### Localization

```bash
cd ml_localization
```

```bash
jupyter notebook localization_ml.ipynb
```

Choose Run All. The first run takes about 5 minutes. The notebook creates `cache/` and `model_extra_trees.joblib`, and overwrites the contents of `figures/`.

## Re-run results

All commands above were run on 2026-11-07 from a copy of this folder with the `.bin` files restored. Versions used: Python 3.12.2, numpy 2.3.5, pandas 2.3.3, scipy 1.16.3, scikit-learn 1.8.0, matplotlib 3.10.8, xgboost 3.2.0.

| Check | Result |
|---|---|
| Tests with raw data | 25 passed |
| `results/tables/coherence_summary.csv` | Byte-identical to the earlier result |
| `eda_windows` and `session_level` output | Matches `ml_people_count/README.md` |
| `eda_people_count.ipynb` | Ran without errors, room 1 numbers match |
| `localization_ml.ipynb` | Text output matches the stored output, except the cache log |

Some numbers in `ml_people_count/README.md` are not printed by the code in this folder, so they could not be re-checked:

- Per-session level features: rho −0.92 and −0.90, then −0.36 and −0.31 after the time control.
- Per-board response: `bf` +0.73 and `d0` −0.51 in room 2.

## Results

### Temporal coherence

Coherence is the autocorrelation of per-subcarrier amplitude, averaged over active subcarriers. The source is `python -m csi_occupancy.coherence`.

| Lag | Room 1 empty | Room 1, 16 people | Room 2 empty | Room 2, 72 people |
|---|---|---|---|---|
| 1 packet | +0.07 | +0.56 | +0.16 | +0.68 |
| ~1 second (40 packets) | +0.06 | +0.40 | +0.02 | +0.51 |
| ~5 seconds (200 packets) | +0.02 | +0.24 | +0.01 | +0.35 |
| ~20 seconds (800 packets) | +0.01 | +0.05 | −0.00 | +0.21 |

Coherence at ~1 second:

- 17 occupied sessions: 0.356–0.572, mean 0.495.
- 2 empty sessions: 0.146 and 0.052.
- Mann-Whitney p = 0.0058, with no overlap.

Among occupied sessions, coherence is unrelated to the number of people: rho +0.16 in room 1 and −0.22 in room 2, neither significant.

### Null controls

Several results look positive with ordinary measures, then collapse once controlled. The numbers below are from room 2.

| Test | Initial result | After control |
|---|---|---|
| Detection, leave-one-session-out | Accuracy 0.933 | Equal to the majority class. `count_2_9` gets 0.000 |
| Cross-session counting | MAE 8.09 people | Mean baseline 9.37, label standard deviation 10.7 |
| Within-session counting, `count_2_1` | MAE 4.10, baseline 5.69 | The shifted-label null gets 3.64, so it is easier |
| Zones | Real layout | Ranks 8, 4, 3, and 20 of 24 permutations |

### Quadrant localization

The protocol is leave-one-lap-out with 456 windows and 169 features.

| Method | Accuracy |
|---|---|
| Random guess | 25.0% |
| Hand-written `argmax` rule | 79.4% |
| MLP | 84.6% |
| Logistic Regression | 85.5% |
| Random Forest | 89.3% |
| XGBoost | 89.7% |
| Extra Trees | 89.9% |

The shuffled-label control gets 25.0%, and labels shuffled within a lap get 24.2%. What is measured is the direction from the router, not distance. This figure applies to unseen laps, not to other days, rooms, or people.

## Analysis rules

1. Do not merge features from the two rooms. Report results per room.
2. Do not split train and test randomly per window. Group by session for occupancy, and by lap for localization.
3. Claims within one session must beat the circularly shifted label null.
4. Classification claims must be compared with the majority class and read per session.
5. Session-level claims must be controlled for session start time.

## Next step

Both datasets share the same flaw: each session holds one nearly constant occupancy level. So "empty or occupied" is always a comparison between sessions.

The most useful recording is one unbroken capture across the end of a class, from 10 minutes before the class ends until 10 minutes after the room is empty. It requires no direction of anyone.

## Things to know

- **The READMEs in the two subfolders are the original notes.** Their contents were not changed. The `cd` commands still point to the original folder, the `import loader` example has been replaced by `csi_occupancy.datasets`, and references to `KNOWLEDGE.md` and the runbooks point to files not included here.
- **Packet rate follows the number of boards.** A board running alone gets 10 Hz, and in four-board sessions each board gets 27–46 Hz. When `bf` died in `count_s01`, the rate of the other three boards fell to about 3/4.
- **Boards capture the same physical frames.** In 5 sessions, 84–99.9% of packets have a counterpart on another board within ±100 µs by hardware `timestamp`. A control with the offset shifted by 7.3 ms gets only 0.4–1.3%. This contradicts the docstring in `tools/csi_merge.py`, lines 8–11. The frame's destination address is not stored, so the idea that these frames are ping replies for other boards is unproven. The script for this check is not in this folder yet.
- **The figure "244 active subcarriers" is imprecise.** Indices 0–2, 64, 126–130, and 192 are always zero. Another 242 indices are nonzero in nearly all packets, and indices 252–255 are nonzero in only 16–58% of packets. Both analyses compute active subcarriers from the data, so their results are unaffected. This index layout differs from the thesis data.
- **Two figures in the original notes do not match their output.** `ml_localization/README.md` gives the within-lap shuffle control as 25.2%, while the notebook prints 24.2%. `ml_people_count/README.md` says classes of 52–72 people in one section, while the room 2 data covers 45–72.
- **`loc_static` is not used by the model.** This recording has no `markers.csv`, so the labels in `figures/static.png` cannot be trusted.
- **Frames have no version field.** If the frame format in the firmware changes, `tools/csi_merge.py` must change with it. A mismatch produces data that parses but is wrong, not an error.

## Code origin

The code was copied from `esp/RISET_CSI_2/` in `CSI-PeopleCounting`. The firmware and recording tools are in [firmware-riset-lanjutan](../firmware-riset-lanjutan/).
