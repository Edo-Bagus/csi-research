# Training dan hasil: skripsi dan paper conference

[English version](README.en.md)

Kode dan hasil untuk mengestimasi jumlah orang di dalam ruangan, dari 0 sampai 6 orang, memakai Channel State Information (CSI) Wi-Fi 6 dari ESP32-C6. Tugas ini dikerjakan dengan dua pendekatan, klasifikasi dan regresi, masing-masing dengan enam model.

Data dikumpulkan dengan firmware di [firmware-skripsi-conference](../firmware-skripsi-conference/).

## Status

Folder ini memuat kode versi final dan hasilnya, tapi belum lengkap.

| Bagian | Status |
|---|---|
| Parsing, merge, dan pembuatan fold | Bisa dijalankan |
| Gambar dari JSON hasil | Bisa dijalankan |
| Ekstraksi fitur dan training | Belum bisa dijalankan |

`preprocess/utils/` belum memuat `parse_file_metadata` dan `compute_sensitivity`, dan belum mengekspor `hampel_filter_per_subcarrier`. Selama bagian ini belum dilengkapi, `featurize_dataset.py` dan 14 dari 15 skrip training berhenti dengan `ImportError`.

## Isi folder

```text
training-skripsi-conference/
├── loader/                       Parsing .bin ke .npz, merge, pembuatan fold
├── preprocess/
│   ├── featurize_dataset.py      Fitur statistik untuk model klasik
│   └── utils/                    Praproses dan windowing
├── train/
│   ├── clf/                      Skrip klasifikasi
│   ├── reg/                      Skrip regresi
│   └── visualize_training_history.py
├── folds/                        Daftar file nested CV
├── result/
│   ├── plot_*.py                 Skrip gambar hasil
│   └── final_result/             JSON hasil final dan gambarnya
└── figures/                      Skrip dan gambar paper
```

Semua file kode dan hasil disalin tanpa perubahan. Dataset, fitur `.npz`, dan model terlatih tidak disertakan.

## Alur

```text
.bin ──> parsing, merge ──> merged.npz ──┬──> window ─────────────────> 1D CNN, LSTM, CNN-LSTM
                                         └──> featurize_dataset.py ───> RF, SVM/SVR, XGBoost
```

| Langkah | Deep learning | Model klasik |
|---|---|---|
| Buang 14 subcarrier tidak aktif | Ya | Ya |
| Imputasi median per subcarrier | Ya | Ya |
| Savitzky-Golay, window 11, orde 3 | Ya | Ya |
| Hampel, radius 7, 3 sigma | Tidak | Ya |
| Window | 100 sampel, stride 50 | 100 sampel, stride 50 |
| Masukan magnitudo | Sekuens (100, 242) | 1210 fitur |
| Masukan magnitudo + fase | Sekuens (100, 484) | 2420 fitur |

Fitur klasik dihitung per subcarrier. Magnitudo memakai mean, simpangan baku, minimum, maksimum, dan median. Fase memakai fase diferensial dengan simpangan baku, rata-rata nilai mutlak, IQR, autokorelasi lag 1, dan nilai mutlak maksimum.

Evaluasi memakai nested cross-validation dengan 4 outer fold dan 3 inner fold. Split dilakukan per file, jadi semua window dari satu rekaman berada di fold yang sama. Hyperparameter dicari dengan random search 10 trial per outer fold, dengan seed 42. Ruang pencarian ada di `HP_SPACE` pada tiap skrip.

## Kebutuhan

- Python 3
- Paket di `requirements.txt`

```bash
pip install -r requirements.txt
```

Training asli memakai RTX 4060 8 GB dan PyTorch 2.6.0 dengan CUDA 12.6 di Windows 11. Versi paket di `requirements.txt` tidak dikunci.

## Menyiapkan data

Semua perintah dijalankan dari folder ini. Perintah berikut memakai Bash, misalnya Git Bash di Windows.

1. Unduh `dataset.zip` dari [Zenodo](https://doi.org/10.5281/zenodo.21467952).
2. Ekstrak di folder ini, sehingga ada `private-dataset/0` sampai `private-dataset/6`.
3. Ubah file `.bin` menjadi `.npz`. Parser membuang 500 paket di awal dan 500 paket di akhir rekaman.

```bash
for f in 0 1 2 3 4 5 6; do python loader/parse_bin_to_npz_v2.py private-dataset/$f --output-dir data/npz/$f --recursive --overwrite; done
```

4. Gabungkan semua rekaman.

```bash
python loader/merge_npz_dataset.py data/npz -o data/merged.npz --recursive --overwrite
```

Hasilnya 58 file dan 922.387 paket, dengan MD5 `fa629f79d0e726a4ba1343d8cea7c659`.

Folder `folds/` sudah disertakan. Perintah berikut membuatnya ulang dengan seed 42 dan hasilnya identik.

```bash
python loader/make_nested_folds_by_filenames.py data/merged.npz --output-dir folds
```

## Melatih model

Bagian ini butuh `preprocess/utils/` yang lengkap. Lihat [Status](#status).

Buat fitur untuk model klasik.

```bash
python preprocess/featurize_dataset.py --merged data/merged.npz --features mag --output preprocess/featurized_dataset_mag.npz
```

```bash
python preprocess/featurize_dataset.py --merged data/merged.npz --features both --output preprocess/featurized_dataset_both.npz
```

Model klasik memilih fitur lewat `--dataset`.

```bash
python train/clf/rf/train_rf_nested.py --dataset preprocess/featurized_dataset_mag.npz --folds-dir folds
```

Model deep learning membaca `merged.npz` langsung.

```bash
python train/clf/cnn/train_cnn_nested.py --merged data/merged.npz --folds-dir folds
```

| Model | Klasifikasi | Regresi |
|---|---|---|
| Random Forest | `train/clf/rf/train_rf_nested.py` | `train/reg/rf/train_rf_nested.py` |
| SVM / SVR | `train/clf/svm/train_svm_nested.py` | `train/reg/SVR/train_svr_nested.py` |
| XGBoost | `train/clf/xgb/train_final_xgb_nested.py` | `train/reg/xgb/train_xgb_nested.py` |
| 1D CNN | `train/clf/cnn/train_cnn_nested.py` | `train/reg/cnn/train_cnn_nested.py` |
| LSTM | `train/clf/lstm/train_lstm_nested.py` | `train/reg/lstm/train_lstm_nested.py` |
| CNN-LSTM | `train/clf/cnn-lstm/train_cnn_lstm_nested.py` | `train/reg/cnn-lstm/train_cnn_lstm_nested.py` |

Konfigurasi magnitudo + fase deep learning memakai skrip `*_phase.py` di folder yang sama.

| Opsi | Arti |
|---|---|
| `--n-trials` | Jumlah trial random search, default 10 |
| `--outer-fold` | Menjalankan satu outer fold saja |

Keluaran ditulis di folder skrip. Hasil training ulang bisa berbeda dari `result/final_result/` karena perangkat dan versi pustaka.

## Hasil

Nilai berikut adalah rata-rata dan simpangan baku dari 4 outer fold.

### Klasifikasi, fitur magnitudo

| Model | Akurasi | F1-macro |
|---|---|---|
| Random Forest | 0,877 ± 0,044 | 0,874 ± 0,056 |
| SVM | 0,893 ± 0,043 | 0,907 ± 0,047 |
| XGBoost | 0,879 ± 0,037 | 0,881 ± 0,046 |
| 1D CNN | 0,936 ± 0,030 | 0,944 ± 0,030 |
| LSTM | 0,905 ± 0,030 | 0,912 ± 0,036 |
| CNN-LSTM | 0,924 ± 0,029 | 0,936 ± 0,023 |

### Regresi

| Model | MAE | RMSE | R² |
|---|---|---|---|
| Random Forest | 0,342 ± 0,062 | 0,574 ± 0,065 | 0,902 ± 0,021 |
| SVR | 0,502 ± 0,067 | 0,691 ± 0,081 | 0,858 ± 0,034 |
| XGBoost | 0,389 ± 0,061 | 0,622 ± 0,062 | 0,885 ± 0,022 |
| 1D CNN | 0,344 ± 0,084 | 0,515 ± 0,114 | 0,919 ± 0,033 |
| LSTM | 0,362 ± 0,047 | 0,547 ± 0,066 | 0,911 ± 0,019 |
| CNN-LSTM | 0,243 ± 0,062 | 0,461 ± 0,120 | 0,934 ± 0,031 |

### Klasifikasi, fitur magnitudo + fase

| Model | Akurasi | F1-macro |
|---|---|---|
| Random Forest | 0,865 ± 0,050 | 0,863 ± 0,063 |
| SVM | 0,864 ± 0,042 | 0,881 ± 0,047 |
| 1D CNN | 0,923 ± 0,041 | 0,936 ± 0,035 |
| LSTM | 0,909 ± 0,016 | 0,917 ± 0,028 |
| CNN-LSTM | 0,919 ± 0,029 | 0,925 ± 0,038 |

Setiap label hanya berasal dari satu kelompok file rekaman, dan kondisi radio tiap label berbeda. Split per file tidak memisahkan sesi rekam, jadi angka di atas belum memisahkan pengaruh jumlah orang dari pengaruh sesi.

### Asal angka di naskah

| Naskah | Sumber |
|---|---|
| Skripsi `tab:klasifikasi_performa`, `tab:klasifikasi_performa_f1kelas`, `tab:stabilitas_clf` | `result/final_result/clf/` |
| Skripsi `tab:regresi_performa`, `tab:stabilitas_reg`, `tab:stabilitas_reg_r2` | `result/final_result/reg/` |
| Skripsi `tab:klasifikasi_vs_regresi`, paper `tab:cls` | `result/final_result/clf/` dan `reg/` |
| Skripsi `tab:ablasi_fitur`, kolom magnitudo + fase | `result/final_result/clf/ablation-phase/` |
| Skripsi `tab:sensitivitas_clf`, `tab:sensitivitas_reg` | Kunci `sensitivity` di JSON |

## Format JSON hasil

| Kunci | Isi |
|---|---|
| `mean_outer_*`, `std_outer_*` | Ringkasan 4 outer fold |
| `outer_folds[i].best_hp` | Hyperparameter terpilih |
| `outer_folds[i].outer_val_metrics` | Metrik, `confusion_matrix`, dan `sensitivity` |
| `outer_folds[i].inner_trials` | Semua trial random search |
| `outer_folds[i].training_history` | Riwayat per epoch, hanya deep learning |

Kunci `sensitivity` memuat metrik per skenario, per zona, dan per kelas.

## Membuat ulang gambar

Skrip ini hanya butuh JSON di `result/final_result/`.

```bash
python result/plot_model_stability.py
```

| Skrip | Keluaran | Dipakai di |
|---|---|---|
| `result/plot_confusion_clf_compare.py` | `result/final_result/confusion_clf_compare.png` | Skripsi `fig:cm_terbaik` |
| `result/plot_confusion_compare.py` | `result/final_result/confusion_compare.png` | Skripsi `fig:confusion_compare` |
| `result/plot_mae_per_class.py` | `result/final_result/mae_per_class.png` | Skripsi `fig:reg_error_kelas` |
| `result/plot_model_stability.py` | `result/final_result/model_stability.png` | Skripsi `fig:genfold` |
| `figures/gen_confusion_compare.py` | `figures/confusion_compare.png` | Paper `fig:cm` |
| `figures/gen_heatmap_sensitivity.py` | `figures/sensitivity_heatmap.png` | Paper `fig:heat` |

Kurva training per fold bisa dilihat dari JSON deep learning.

```bash
python -X utf8 train/visualize_training_history.py result/final_result/clf/nested_cv_result_cnn.json --save cnn.png
```

## Dataset

Dataset terbit di Zenodo: [10.5281/zenodo.21467952](https://doi.org/10.5281/zenodo.21467952).

## Asal kode

Kode berasal dari repositori [CSI-ML](https://github.com/Edo-Bagus/CSI-ML), commit `ff71279`.
