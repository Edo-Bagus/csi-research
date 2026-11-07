"""Satu-satunya tempat yang tahu di mana file berada.

KENAPA FILE INI ADA
-------------------
Sebelum refactor, tiap skrip menghitung sendiri lokasi datanya dengan
`os.path.dirname(os.path.abspath(__file__))` lalu menempelkan nama folder.
Akibatnya memindahkan satu folder berarti mengedit empat file, dan skrip hanya
jalan kalau dijalankan dari direktori yang tepat.

Sekarang semua jalur berasal dari `PROJECT_ROOT` yang dihitung sekali, relatif
terhadap posisi file ini di dalam paket. Jadi skrip bisa dijalankan dari mana pun.

Tata letak yang diasumsikan:

    ml_people_count/
      data/raw/<dataset>/<sesi>/*.bin,*.csv   <- data mentah, JANGAN diubah
      data/processed/                         <- cache fitur, boleh dihapus
      results/tables/                         <- CSV hasil analisis
      results/figures/                        <- gambar
      src/csi_occupancy/                      <- paket ini
"""
from pathlib import Path

# paths.py -> csi_occupancy -> src -> ml_people_count
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
RESULTS = PROJECT_ROOT / "results"
RESULTS_TABLES = RESULTS / "tables"
RESULTS_FIGURES = RESULTS / "figures"

# Definisi frame .bin hidup di tools/csi_merge.py dan TIDAK disalin ke sini.
# Format frame tidak punya version field, jadi salinan struct akan gagal
# diam-diam saat firmware berubah: file tetap terbaca, angkanya saja ngawur.
TOOLS_DIR = (PROJECT_ROOT / ".." / "tools").resolve()


def ensure_output_dirs():
    """Buat folder keluaran kalau belum ada. Aman dipanggil berulang."""
    for d in (DATA_PROCESSED, RESULTS_TABLES, RESULTS_FIGURES):
        d.mkdir(parents=True, exist_ok=True)
