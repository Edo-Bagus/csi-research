"""Tes yang membaca data mentah: fitur per-jendela dan invarian analisis.

Ditandai `needs_data` + `slow` karena membaca .bin. Lewati dengan:
    pytest -m "not needs_data"
"""
import numpy as np
import pytest

from csi_occupancy import STATS, ZONES, window_features

pytestmark = [pytest.mark.needs_data, pytest.mark.slow]


def test_dead_board_is_dropped_not_used_to_truncate(ds_14_9):
    """count_s01: board bf mati setelah 11 detik dari 293.

    Irisan naif "semua board hidup" pernah menyisakan 9 jendela dan membuang
    97% sesi TANPA pesan error. Yang benar: buang board-nya, bukan sesinya.
    """
    f = window_features("count_s01", ds=ds_14_9)
    assert "bf" in f["dropped_boards"].iloc[0]
    assert f["n_boards"].iloc[0] == 3
    # sesi ~293 s, hop 1 s -> harus ratusan jendela, bukan belasan
    assert len(f) > 200, f"hanya {len(f)} jendela -- sesi ikut terpotong"


def test_dataset_column_identifies_room(ds_15_9):
    """Kolom `dataset` wajib ada: itu satu-satunya cara memisahkan kembali dua
    ruangan kalau tabelnya pernah digabung. Menggabung fitur dua ruangan
    mencampur efek ruangan dengan efek jumlah orang."""
    f = window_features("count_2_6", ds=ds_15_9)
    assert f["dataset"].unique().tolist() == ["data-15-9"]


def test_all_four_boards_present_in_15_9(ds_15_9):
    """Ruangan 2 punya 4 board utuh di semua sesi -- klaim di README."""
    f = window_features("count_2_6", ds=ds_15_9)
    assert f["n_boards"].iloc[0] == 4
    assert f["boards"].iloc[0] == "38,4b,bf,d0"
    assert f["dropped_boards"].iloc[0] == ""


def test_feature_columns_exist_per_board(ds_15_9):
    f = window_features("count_2_6", ds=ds_15_9)
    for tag in ["38", "4b", "bf", "d0"]:
        for stat in STATS:
            assert f"{tag}_{stat}" in f.columns, f"{tag}_{stat} hilang"


def test_labels_are_never_silently_zero_filled(ds_15_9):
    """Jendela di luar rentang pencatat harus NaN, bukan 0."""
    f = window_features("count_2_6", ds=ds_15_9)
    assert f["total"].isna().any(), "tidak ada NaN sama sekali -- dicurigai diisi 0"
    for c in ZONES + ["total"]:
        assert f[c].dropna().ge(0).all()


def test_windows_are_time_ordered_and_evenly_spaced(ds_15_9):
    f = window_features("count_2_6", ds=ds_15_9, win_s=2.0, hop_s=1.0)
    t = f["t_start"].to_numpy()
    assert (np.diff(t) > 0).all(), "jendela tidak urut waktu"
    assert np.allclose(np.diff(t), 1.0, atol=1e-6), "hop bukan 1 s"


def test_normalize_empty_uses_own_rooms_baseline(ds_15_9):
    """normalize="empty" harus memakai sesi kosong ruangan ITU SENDIRI.

    Cache baseline dulu di-key pada data_dir; itu jalur nyata untuk baseline
    ruangan 1 bocor ke ruangan 2.
    """
    raw = window_features("count_2_6", ds=ds_15_9, normalize="none")
    nrm = window_features("count_2_6", ds=ds_15_9, normalize="empty")
    c = "4b_sub_var"
    # ternormalisasi harus berbeda dari mentah, dan terpusat jauh lebih dekat ke 0
    assert not np.allclose(raw[c].dropna(), nrm[c].dropna())
    assert abs(np.nanmedian(nrm[c])) < abs(np.nanmedian(raw[c]))


def test_unknown_normalize_is_rejected(ds_15_9):
    with pytest.raises(ValueError, match="normalize"):
        window_features("count_2_6", ds=ds_15_9, normalize="tidak-ada")
