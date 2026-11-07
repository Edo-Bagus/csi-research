# Training and results: thesis and conference paper

[Versi Bahasa Indonesia](README.md)

Code and results for estimating the number of people in a room, from 0 to 6, using Wi-Fi 6 Channel State Information (CSI) from ESP32-C6 boards. The task is approached in two ways, classification and regression, with six models each.

The data was collected with the firmware in [firmware-skripsi-conference](../firmware-skripsi-conference/).

## Status

This folder holds the final code version and its results, but it is not complete yet.

| Part | Status |
|---|---|
| Parsing, merging, and fold creation | Runs |
| Figures from the result JSON files | Runs |
| Feature extraction and training | Does not run yet |

`preprocess/utils/` does not yet contain `parse_file_metadata` and `compute_sensitivity`, and does not yet export `hampel_filter_per_subcarrier`. Until this is completed, `featurize_dataset.py` and 14 of the 15 training scripts stop with an `ImportError`.

## Folder contents

```text
training-skripsi-conference/
├── loader/                       Parse .bin to .npz, merge, create folds
├── preprocess/
│   ├── featurize_dataset.py      Statistical features for classical models
│   └── utils/                    Preprocessing and windowing
├── train/
│   ├── clf/                      Classification scripts
│   ├── reg/                      Regression scripts
│   └── visualize_training_history.py
├── folds/                        Nested CV file lists
├── result/
│   ├── plot_*.py                 Result figure scripts
│   └── final_result/             Final result JSON files and their figures
└── figures/                      Paper figure scripts and images
```

All code and result files were copied unchanged. The dataset, `.npz` features, and trained models are not included.

## Pipeline

```text
.bin ──> parsing, merge ──> merged.npz ──┬──> windowing ──────────────> 1D CNN, LSTM, CNN-LSTM
                                         └──> featurize_dataset.py ───> RF, SVM/SVR, XGBoost
```

| Step | Deep learning | Classical models |
|---|---|---|
| Drop 14 inactive subcarriers | Yes | Yes |
| Median imputation per subcarrier | Yes | Yes |
| Savitzky-Golay, window 11, order 3 | Yes | Yes |
| Hampel, radius 7, 3 sigma | No | Yes |
| Window | 100 samples, stride 50 | 100 samples, stride 50 |
| Magnitude input | Sequence (100, 242) | 1210 features |
| Magnitude + phase input | Sequence (100, 484) | 2420 features |

Classical features are computed per subcarrier. Magnitude uses the mean, standard deviation, minimum, maximum, and median. Phase uses differential phase with the standard deviation, mean absolute value, IQR, lag-1 autocorrelation, and maximum absolute value.

Evaluation uses nested cross-validation with 4 outer folds and 3 inner folds. Splits are made per file, so all windows from one recording stay in the same fold. Hyperparameters are found by a 10-trial random search per outer fold, with seed 42. The search spaces are in `HP_SPACE` in each script.

## Requirements

- Python 3
- The packages in `requirements.txt`

```bash
pip install -r requirements.txt
```

The original training used an RTX 4060 8 GB and PyTorch 2.6.0 with CUDA 12.6 on Windows 11. Package versions in `requirements.txt` are not pinned.

## Preparing the data

Run all commands from this folder. The commands below use Bash, for example Git Bash on Windows.

1. Download `dataset.zip` from [Zenodo](https://doi.org/10.5281/zenodo.21467952).
2. Extract it in this folder, so that `private-dataset/0` to `private-dataset/6` exist.
3. Convert the `.bin` files to `.npz`. The parser drops 500 packets at the start and 500 packets at the end of each recording.

```bash
for f in 0 1 2 3 4 5 6; do python loader/parse_bin_to_npz_v2.py private-dataset/$f --output-dir data/npz/$f --recursive --overwrite; done
```

4. Merge all recordings.

```bash
python loader/merge_npz_dataset.py data/npz -o data/merged.npz --recursive --overwrite
```

The result has 58 files and 922,387 packets, with MD5 `fa629f79d0e726a4ba1343d8cea7c659`.

The `folds/` folder is included. The command below recreates it with seed 42, and the result is identical.

```bash
python loader/make_nested_folds_by_filenames.py data/merged.npz --output-dir folds
```

## Training the models

This section needs a complete `preprocess/utils/`. See [Status](#status).

Create the features for the classical models.

```bash
python preprocess/featurize_dataset.py --merged data/merged.npz --features mag --output preprocess/featurized_dataset_mag.npz
```

```bash
python preprocess/featurize_dataset.py --merged data/merged.npz --features both --output preprocess/featurized_dataset_both.npz
```

Classical models select their features with `--dataset`.

```bash
python train/clf/rf/train_rf_nested.py --dataset preprocess/featurized_dataset_mag.npz --folds-dir folds
```

Deep learning models read `merged.npz` directly.

```bash
python train/clf/cnn/train_cnn_nested.py --merged data/merged.npz --folds-dir folds
```

| Model | Classification | Regression |
|---|---|---|
| Random Forest | `train/clf/rf/train_rf_nested.py` | `train/reg/rf/train_rf_nested.py` |
| SVM / SVR | `train/clf/svm/train_svm_nested.py` | `train/reg/SVR/train_svr_nested.py` |
| XGBoost | `train/clf/xgb/train_final_xgb_nested.py` | `train/reg/xgb/train_xgb_nested.py` |
| 1D CNN | `train/clf/cnn/train_cnn_nested.py` | `train/reg/cnn/train_cnn_nested.py` |
| LSTM | `train/clf/lstm/train_lstm_nested.py` | `train/reg/lstm/train_lstm_nested.py` |
| CNN-LSTM | `train/clf/cnn-lstm/train_cnn_lstm_nested.py` | `train/reg/cnn-lstm/train_cnn_lstm_nested.py` |

The deep learning magnitude + phase configuration uses the `*_phase.py` scripts in the same folders.

| Option | Meaning |
|---|---|
| `--n-trials` | Number of random search trials, default 10 |
| `--outer-fold` | Run a single outer fold |

Outputs are written to the script's folder. Retrained results can differ from `result/final_result/` because of hardware and library versions.

## Results

The values below are the mean and standard deviation over the 4 outer folds.

### Classification, magnitude features

| Model | Accuracy | F1-macro |
|---|---|---|
| Random Forest | 0.877 ± 0.044 | 0.874 ± 0.056 |
| SVM | 0.893 ± 0.043 | 0.907 ± 0.047 |
| XGBoost | 0.879 ± 0.037 | 0.881 ± 0.046 |
| 1D CNN | 0.936 ± 0.030 | 0.944 ± 0.030 |
| LSTM | 0.905 ± 0.030 | 0.912 ± 0.036 |
| CNN-LSTM | 0.924 ± 0.029 | 0.936 ± 0.023 |

### Regression

| Model | MAE | RMSE | R² |
|---|---|---|---|
| Random Forest | 0.342 ± 0.062 | 0.574 ± 0.065 | 0.902 ± 0.021 |
| SVR | 0.502 ± 0.067 | 0.691 ± 0.081 | 0.858 ± 0.034 |
| XGBoost | 0.389 ± 0.061 | 0.622 ± 0.062 | 0.885 ± 0.022 |
| 1D CNN | 0.344 ± 0.084 | 0.515 ± 0.114 | 0.919 ± 0.033 |
| LSTM | 0.362 ± 0.047 | 0.547 ± 0.066 | 0.911 ± 0.019 |
| CNN-LSTM | 0.243 ± 0.062 | 0.461 ± 0.120 | 0.934 ± 0.031 |

### Classification, magnitude + phase features

| Model | Accuracy | F1-macro |
|---|---|---|
| Random Forest | 0.865 ± 0.050 | 0.863 ± 0.063 |
| SVM | 0.864 ± 0.042 | 0.881 ± 0.047 |
| 1D CNN | 0.923 ± 0.041 | 0.936 ± 0.035 |
| LSTM | 0.909 ± 0.016 | 0.917 ± 0.028 |
| CNN-LSTM | 0.919 ± 0.029 | 0.925 ± 0.038 |

Each label comes from a single group of recording files, and the radio conditions differ per label. Per-file splits do not separate recording sessions, so the numbers above do not yet separate the effect of the number of people from the effect of the session.

### Where the manuscript numbers come from

| Manuscript | Source |
|---|---|
| Thesis `tab:klasifikasi_performa`, `tab:klasifikasi_performa_f1kelas`, `tab:stabilitas_clf` | `result/final_result/clf/` |
| Thesis `tab:regresi_performa`, `tab:stabilitas_reg`, `tab:stabilitas_reg_r2` | `result/final_result/reg/` |
| Thesis `tab:klasifikasi_vs_regresi`, paper `tab:cls` | `result/final_result/clf/` and `reg/` |
| Thesis `tab:ablasi_fitur`, magnitude + phase columns | `result/final_result/clf/ablation-phase/` |
| Thesis `tab:sensitivitas_clf`, `tab:sensitivitas_reg` | The `sensitivity` key in the JSON files |

## Result JSON format

| Key | Content |
|---|---|
| `mean_outer_*`, `std_outer_*` | Summary over the 4 outer folds |
| `outer_folds[i].best_hp` | Selected hyperparameters |
| `outer_folds[i].outer_val_metrics` | Metrics, `confusion_matrix`, and `sensitivity` |
| `outer_folds[i].inner_trials` | All random search trials |
| `outer_folds[i].training_history` | Per-epoch history, deep learning only |

The `sensitivity` key holds metrics per scenario, per zone, and per class.

## Recreating the figures

These scripts only need the JSON files in `result/final_result/`.

```bash
python result/plot_model_stability.py
```

| Script | Output | Used in |
|---|---|---|
| `result/plot_confusion_clf_compare.py` | `result/final_result/confusion_clf_compare.png` | Thesis `fig:cm_terbaik` |
| `result/plot_confusion_compare.py` | `result/final_result/confusion_compare.png` | Thesis `fig:confusion_compare` |
| `result/plot_mae_per_class.py` | `result/final_result/mae_per_class.png` | Thesis `fig:reg_error_kelas` |
| `result/plot_model_stability.py` | `result/final_result/model_stability.png` | Thesis `fig:genfold` |
| `figures/gen_confusion_compare.py` | `figures/confusion_compare.png` | Paper `fig:cm` |
| `figures/gen_heatmap_sensitivity.py` | `figures/sensitivity_heatmap.png` | Paper `fig:heat` |

Per-fold training curves can be read from the deep learning JSON files.

```bash
python -X utf8 train/visualize_training_history.py result/final_result/clf/nested_cv_result_cnn.json --save cnn.png
```

## Dataset

The dataset is published on Zenodo: [10.5281/zenodo.21467952](https://doi.org/10.5281/zenodo.21467952).

## Code origin

The code comes from the [CSI-ML](https://github.com/Edo-Bagus/CSI-ML) repository, commit `ff71279`.
