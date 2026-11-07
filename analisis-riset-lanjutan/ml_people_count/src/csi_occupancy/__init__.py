"""Analisis okupansi ruang kelas dari CSI WiFi komoditas (ESP32-C6).

Dua dataset, DUA RUANG KELAS BERBEDA. Jangan pernah menggabung fiturnya:
itu mencampur efek ruangan dengan efek jumlah orang. Lihat `datasets.DS_14_9`
dan `datasets.DS_15_9`, dan README untuk hasil yang berlaku.

Pintu masuk yang biasa dipakai:

    from csi_occupancy import DS_15_9, window_features
    f = window_features("count_2_4", ds=DS_15_9)

Analisis yang bisa dijalankan sebagai modul:

    python -m csi_occupancy.coherence        # hasil utama
    python -m csi_occupancy.session_level    # tingkat sesi, kedua ruangan
    python -m csi_occupancy.eda_windows      # EDA per jendela + kontrol null
"""
from .datasets import (  # noqa: F401
    DATASETS,
    DEFAULT,
    DS_14_9,
    DS_15_9,
    STATS,
    ZONES,
    Dataset,
    empty_baseline,
    label_at,
    list_sessions,
    load_events,
    load_occupancy,
    load_session,
    node_tag,
    read_node,
    resolve,
    window_features,
)
from .paths import (  # noqa: F401
    DATA_PROCESSED,
    DATA_RAW,
    PROJECT_ROOT,
    RESULTS_FIGURES,
    RESULTS_TABLES,
)

__all__ = [
    "Dataset", "DS_14_9", "DS_15_9", "DATASETS", "DEFAULT", "resolve",
    "ZONES", "STATS", "node_tag", "read_node", "load_session", "list_sessions",
    "load_occupancy", "load_events", "label_at", "window_features",
    "empty_baseline",
    "PROJECT_ROOT", "DATA_RAW", "DATA_PROCESSED",
    "RESULTS_TABLES", "RESULTS_FIGURES",
]
