"""Tes untuk kekeliruan yang GAGAL DIAM-DIAM di proyek ini.

Tiap tes di sini menjaga satu kesalahan nyata yang pernah terjadi atau yang
strukturnya memungkinkan. Yang dijaga bukan "apakah kodenya jalan" (itu terlihat
sendiri) tapi "apakah kodenya jalan dengan angka yang BENAR" — karena semua
kesalahan di bawah ini tidak memunculkan error apa pun.
"""
import numpy as np
import pandas as pd
import pytest

from csi_occupancy import (DATASETS, DS_14_9, DS_15_9, ZONES, Dataset,
                           label_at, resolve)


# ---------------------------------------------------- denah zona per ruangan

def test_two_rooms_have_different_zone_maps():
    """C dan D tertukar antar ruangan. Kalau ini sama, salah satu ruangan salah.

    Frame .bin tidak punya version field dan nama file hanya memuat node_id,
    jadi denah yang tertukar menghasilkan angka zona salah TANPA error.
    """
    assert DS_14_9.zone_board["C"] == "38"
    assert DS_14_9.zone_board["D"] == "4b"
    assert DS_15_9.zone_board["C"] == "4b"
    assert DS_15_9.zone_board["D"] == "38"
    assert DS_14_9.zone_board != DS_15_9.zone_board


def test_zone_maps_are_bijective():
    """Tiap board tepat satu zona. Denah yang dobel bikin board hilang senyap."""
    for ds in DATASETS.values():
        assert sorted(ds.zone_board) == ZONES
        boards = list(ds.zone_board.values())
        assert len(set(boards)) == len(boards), f"{ds.name}: board dobel"
        # board_zone harus benar-benar kebalikannya
        for z, b in ds.zone_board.items():
            assert ds.board_zone[b] == z


def test_empty_session_is_per_room():
    """Baseline kosong ruangan 1 tidak boleh dipakai untuk ruangan 2."""
    assert DS_14_9.empty_session == "count_s10"
    assert DS_15_9.empty_session == "count_2_9"
    assert DS_14_9.empty_session != DS_15_9.empty_session


# ------------------------------------------------------------------- resolve

def test_resolve_accepts_object_name_and_path():
    assert resolve(DS_15_9) is DS_15_9
    assert resolve("data-15-9") is DS_15_9
    assert resolve(DS_15_9.data_dir).name == "data-15-9"
    assert resolve(None) is DS_14_9          # default = ruangan 1


def test_resolve_warns_on_unknown_dataset():
    """Dataset tak terdaftar dapat denah default -- itu HARUS berisik.

    Kalau ruangan ketiga ditambahkan lalu dipakai lewat path mentah, denah
    ruangan 1 akan dipakai dan angka zonanya salah tanpa error.
    """
    with pytest.warns(UserWarning, match="tidak dikenal"):
        resolve("data-99-9")


def test_unknown_dataset_has_no_empty_session():
    """Tanpa sesi kosong terdaftar, normalize="empty" harus MENOLAK, bukan
    diam-diam memakai sesi kosong ruangan lain."""
    with pytest.warns(UserWarning):
        d = resolve("data-99-9")
    assert d.empty_session is None


def test_empty_baseline_refuses_without_empty_session():
    from csi_occupancy import empty_baseline
    bad = Dataset(name="x", dirname="x", zone_board={}, empty_session=None)
    with pytest.raises(ValueError, match="sesi ruangan kosong"):
        empty_baseline(ds=bad)


# --------------------------------------------------------- label join (host_time)

def _occ(rows):
    return pd.DataFrame(rows, columns=["t_start", "t_end", *ZONES, "total"])


def test_label_at_uses_intervals_not_nearest():
    """Label adalah interval [t_start, t_end). Pernah salah dijoin lewat t_rel,
    yang menggeser SELURUH label beberapa detik tanpa error."""
    occ = _occ([
        (100.0, 110.0, 1, 0, 0, 0, 1),
        (110.0, 120.0, 2, 0, 0, 0, 2),
        (120.0, 130.0, 3, 0, 0, 0, 3),
    ])
    lab = label_at(occ, [105.0, 110.0, 119.999, 125.0])
    assert lab["total"].tolist() == [1.0, 2.0, 2.0, 3.0]


def test_label_at_returns_nan_outside_range_not_zero():
    """Di luar rentang pencatat -> NaN. Mengisi 0 berarti mengklaim "kosong"
    padahal yang benar "tidak tercatat" -- itu label palsu."""
    occ = _occ([(100.0, 110.0, 1, 0, 0, 0, 1)])
    lab = label_at(occ, [90.0, 105.0, 200.0])
    assert np.isnan(lab["total"].iloc[0])
    assert lab["total"].iloc[1] == 1.0
    assert np.isnan(lab["total"].iloc[2])


def test_label_at_all_zone_columns_present():
    occ = _occ([(100.0, 110.0, 1, 2, 3, 4, 10)])
    lab = label_at(occ, [105.0])
    for c in ZONES + ["total"]:
        assert c in lab.columns
    assert lab[["A", "B", "C", "D"]].iloc[0].tolist() == [1.0, 2.0, 3.0, 4.0]


# ------------------------------------------------------------------ node tag

def test_node_tag_uses_node_id_not_mac_byte():
    """Tag board berasal dari node_id, BUKAN byte terakhir MAC. Firmware
    mem-fold dua byte terakhir MAC (0x0b ^ 0x40 = 0x4b), jadi tag turunan MAC
    diam-diam salah."""
    from csi_occupancy import node_tag
    assert node_tag({"node_id": 0x4b}) == "4b"
    assert node_tag({"node_id": 0xd0}) == "d0"
    assert node_tag({"node_id": 0x38}) == "38"
