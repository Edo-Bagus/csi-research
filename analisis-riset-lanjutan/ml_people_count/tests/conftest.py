"""Fixture bersama + skip otomatis kalau data mentah tidak ada.

Data mentah 1.4 GB tidak ikut ke git, jadi tes yang membacanya harus melewati
diri sendiri di mesin yang belum punya data — bukan gagal. Tes yang murni
logika (tanpa data) tetap jalan di mana pun.
"""
import pytest

from csi_occupancy import DS_14_9, DS_15_9
from csi_occupancy.paths import DATA_RAW


def _has(ds):
    import os
    return os.path.isdir(ds.data_dir) and bool(os.listdir(ds.data_dir))


needs_data = pytest.mark.skipif(
    not DATA_RAW.is_dir(),
    reason="data/raw/ tidak ada di mesin ini",
)


@pytest.fixture(scope="session")
def ds_14_9():
    if not _has(DS_14_9):
        pytest.skip("data-14-9 tidak ada")
    return DS_14_9


@pytest.fixture(scope="session")
def ds_15_9():
    if not _has(DS_15_9):
        pytest.skip("data-15-9 tidak ada")
    return DS_15_9
