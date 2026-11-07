# Urutan menjalankan analisis. Dipakai lewat `make <target>`.
# Di Windows tanpa make, jalankan perintah di kanan target secara manual --
# semuanya satu baris `python -m ...`.

.PHONY: help setup test test-fast all coherence session eda notebook clean clean-all

help:
	@echo "setup      - pasang paket (editable) + dependensi dev"
	@echo "test       - seluruh tes (butuh data/raw/)"
	@echo "test-fast  - tes yang tidak butuh data mentah"
	@echo "all        - jalankan ketiga analisis, urut"
	@echo "coherence  - HASIL UTAMA: koherensi temporal"
	@echo "session    - analisis tingkat sesi, kedua ruangan"
	@echo "eda        - EDA per jendela + kontrol null (ruangan 2)"
	@echo "notebook   - bangun ulang notebook dari nb_cells.py"
	@echo "clean      - hapus cache fitur (bisa dibuat ulang)"

setup:
	python -m pip install -e ".[dev]"

test:
	python -m pytest tests/ -v

test-fast:
	python -m pytest tests/ -v -m "not needs_data"

# Urutannya penting HANYA untuk kecepatan: eda membangun cache fitur yang
# dipakai lagi oleh session dan coherence. Hasilnya sama kalau urutannya lain.
all: eda session coherence

eda:
	python -m csi_occupancy.eda_windows

session:
	python -m csi_occupancy.session_level

coherence:
	python -m csi_occupancy.coherence

notebook:
	cd notebooks && python build_nb.py

clean:
	rm -rf data/processed/*.csv

clean-all: clean
	rm -rf .pytest_cache src/*.egg-info
	find . -name __pycache__ -type d -exec rm -rf {} +
