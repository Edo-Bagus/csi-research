"""
Perbandingan confusion matrix model klasifikasi terbaik: 1D CNN vs SVM.

Confusion matrix per outer-fold pada hasil nested-CV dijumlahkan (agregat)
melintasi keempat outer-fold, lalu kedua model digambar berdampingan (1x2).
Setiap sel menampilkan RECALL (dinormalisasi per baris / kelas sebenarnya) di
baris atas dan jumlah window mentah dalam tanda kurung di bawahnya; WARNA sel
mengikuti recall sehingga dominasi diagonal terbaca jelas tanpa terpengaruh
ketidakseimbangan kelas.

  * kiri  : 1D CNN
  * kanan : SVM

Output: final_result/confusion_clf_compare.png  (dan .svg)

Jalankan:
    python result/plot_confusion_clf_compare.py
"""

import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

# --------------------------------------------------------------------------- #
# Konfigurasi
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "final_result"
CNN_FILE = RESULT_DIR / "clf" / "nested_cv_result_cnn.json"
SVM_FILE = RESULT_DIR / "clf" / "nested_cv_result_svm.json"
OUT_PATH = RESULT_DIR / "confusion_clf_compare.png"

# Label kelas = jumlah orang (7 kelas -> 0..6).
CLASS_LABELS = [str(i) for i in range(7)]

CMAP = "Blues"

# Perbesar semua teks.
plt.rcParams.update({
    "font.size": 16,
    "axes.titlesize": 22,
    "axes.labelsize": 18,
    "xtick.labelsize": 15,
    "ytick.labelsize": 15,
    "figure.titlesize": 24,
})


# --------------------------------------------------------------------------- #
# Pemuatan data
# --------------------------------------------------------------------------- #
def aggregate_cm(path: Path) -> np.ndarray:
    """Jumlahkan confusion matrix tiap outer-fold menjadi satu matriks."""
    data = json.loads(path.read_text())
    cms = [
        np.asarray(f["outer_val_metrics"]["confusion_matrix"], dtype=int)
        for f in data["outer_folds"]
    ]
    return np.sum(cms, axis=0)


# --------------------------------------------------------------------------- #
# Penggambaran
# --------------------------------------------------------------------------- #
def draw_cm(ax, cm, labels, cmap, title):
    n = cm.shape[0]
    row_sums = cm.sum(axis=1, keepdims=True)
    recall = np.divide(cm, row_sums, where=row_sums != 0)  # recall per kelas

    im = ax.imshow(recall, cmap=cmap, vmin=0, vmax=1, aspect="equal")

    # anotasi tiap sel: recall (atas) + jumlah window (bawah); warna ikut recall
    thresh = 0.5
    for i in range(n):
        for j in range(n):
            color = "white" if recall[i, j] > thresh else "black"
            ax.text(
                j, i,
                f"{recall[i, j]:.2f}\n({cm[i, j]})",
                ha="center", va="center",
                color=color, fontsize=12,
            )

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Prediksi (jumlah orang)")
    ax.set_ylabel("Aktual (jumlah orang)")

    acc = np.trace(cm) / cm.sum()
    ax.set_title(f"{title}\nakurasi agregat = {acc:.3f}", pad=14)
    return im


def main():
    cnn_cm = aggregate_cm(CNN_FILE)
    svm_cm = aggregate_cm(SVM_FILE)

    fig, (ax_cnn, ax_svm) = plt.subplots(1, 2, figsize=(18, 9))

    im_cnn = draw_cm(ax_cnn, cnn_cm, CLASS_LABELS, CMAP, title="1D CNN")
    im_svm = draw_cm(ax_svm, svm_cm, CLASS_LABELS, CMAP, title="SVM")

    fig.colorbar(im_cnn, ax=ax_cnn, fraction=0.046, pad=0.04, label="recall")
    fig.colorbar(im_svm, ax=ax_svm, fraction=0.046, pad=0.04, label="recall")

    fig.suptitle(
        "Confusion matrix agregat (4 outer-fold) — 1D CNN vs SVM",
        y=0.98,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    fig.savefig(OUT_PATH, dpi=400, bbox_inches="tight")
    fig.savefig(OUT_PATH.with_suffix(".svg"), bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")
    print(f"Saved: {OUT_PATH.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
