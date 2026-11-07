# Lokalisasi Kuadran dari CSI — Model Pembelajaran Mesin

Model terlatih untuk menjawab: **dari empat board ESP32 di sudut ruangan, di kuadran mana
orang berada?**

Folder ini mandiri — data capture sudah disalin ke `data/`, jadi seluruh analisis bisa
dijalankan ulang tanpa bergantung pada `../capture/`.

## Hasil

Protokol: **leave-one-lap-out** (8 lipatan, satu per lap), 456 jendela berlabel, 169 fitur.

| Metode | Akurasi |
|---|---|
| Tebakan acak | 25,0% |
| MLP | 84,6% |
| Logistic Regression | 85,5% |
| Random Forest | 89,3% |
| XGBoost | 89,7% |
| **Extra Trees** | **89,9%** |
| *Aturan `argmax` tangan (pembanding)* | *79,4%* |

Peningkatan **+10,5 poin** atas aturan tangan; 51% dari sisa kesalahan terhapus.
Holdout lap 1–4 → 5–8: **93,0%**.

Per kelas: `38` 95%, `d0` 92%, `4b` 87%, `bf` 85%.
Kesalahan: **83% ke sudut tetangga**, hanya 17% ke sudut seberang — pola yang diharapkan
dari penaksir arah.

Kontrol: label diacak 25,0%, diacak dalam lap 25,2% (keduanya tepat di garis tebakan
acak, jadi tidak ada kebocoran).

### Tiga temuan untuk skripsi

1. **Yang menaikkan akurasi adalah fiturnya, bukan pengklasifikasinya.** Model yang hanya
   diberi 4 fitur variance — informasi yang sama dengan aturan lama — hanya mencapai
   **62,3%**, yaitu *lebih buruk* daripada aturan `argmax` (79,4%). Peningkatan baru
   muncul setelah ringkasan per pita subcarrier (35% importance) dan turunan waktu (32%)
   ditambahkan.
2. **Board paling tidak peka justru paling akurat.** `38` nyaris tidak merespons pada
   fitur mentah (z≈0,32 di sudutnya sendiri) tetapi akurasi per kelasnya tertinggi (95%).
   Model bisa memberi bobot berbeda per board; `argmax` tidak bisa.
3. **Amplitudo rata-rata hampir tidak berguna** (2% importance) — kehadiran orang terbaca
   dari *sebaran* kanal, bukan dari *level*-nya.

Penghalusan optimal 4 detik (sapuan: 0 s → 70,2%, 4 s → 89,9%, 12 s → 87,3%), sesuai
dugaan bahwa seperempat lap ≈ 7 detik menjadi batas atasnya.

## Isi

| Berkas | Isi |
|---|---|
| `localization_ml.ipynb` | Notebook utama: fitur, model, kontrol, gambar |
| `features.py` | Ekstraksi fitur dari `.bin` mentah (dipakai notebook) |
| `data/` | Salinan capture 2026-09-09 (~83 MB, tidak masuk git) |
| `cache/` | Cache fitur `.npz`, dibuat otomatis |
| `figures/` | Gambar hasil, dibuat otomatis |

## Menjalankan

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2\ml_localization
jupyter notebook localization_ml.ipynb
```

Lalu Run All. Jalan pertama membaca ~83 MB `.bin` (sekitar satu menit); sesudahnya fitur
diambil dari `cache/`. Bagian 9 (sapuan penghalusan) membangun ulang fitur untuk tujuh
nilai, jadi bagian itu paling lama.

Kebutuhan: `numpy`, `pandas`, `scikit-learn`, `xgboost`, `matplotlib`, `joblib` — semuanya
sudah ada di environment yang dipakai.

## Ringkas metode

```
.bin (4 board, ~38 Hz)
   -> jendela 500 ms, min 8 paket, harus terisi di SEMUA board
   -> 20 fitur per board (amplitudo, pita subcarrier, turunan waktu, RSSI)
   -> normalisasi z terhadap capture ruangan KOSONG (median/MAD per board)
   -> fitur konteks antar board (peringkat, proporsi)
   -> penghalusan 4 detik
   -> klasifikasi 4 kelas
```

Total 169 fitur per jendela, 456 jendela berlabel dari 8 lap.

## Tiga hal yang menentukan hasil

**1. Normalisasi per board itu wajib.** Sensitivitas board berbeda jauh (rata-rata z di
sudutnya sendiri: 3,27 untuk `d0` tapi hanya 0,46 untuk `38`). Tanpa normalisasi, board
paling peka menang di mana-mana.

**2. Pembagian train/test harus dikelompokkan per lap.** Jendela berjarak 500 ms dan
dihaluskan 4 detik, jadi jendela bertetangga hampir merupakan pengukuran yang sama.
Pembagian acak per jendela membocorkan data — notebook menjalankannya sengaja di Bagian 7
untuk memperlihatkan selisihnya.

**3. `loc_static` tidak dipakai.** Penandaan waktunya tidak sesuai rencana dan tidak ada
`markers.csv`, jadi labelnya tidak bisa dipercaya. Capture itu dulu dipakai untuk
mempelajari polaritas, tetapi fitur berbasis sebaran tidak punya ambiguitas polaritas —
kehadiran orang selalu membuat variance naik. Datanya tetap disalin ke `data/` untuk
kelengkapan, tidak untuk dipakai.

## Batas yang harus ditulis di skripsi

1. **Arah, bukan jarak.** Semua board menerima dari router yang sama di tengah ruangan,
   jadi yang terukur adalah perpotongan orang dengan garis `router->board`. Berdiri di
   tengah jalur dan berdiri di sudut menghasilkan gangguan yang mirip.
2. **Satu sesi, 8 lap, satu orang.** Angka leave-one-lap-out sah untuk lap yang belum
   dilihat — bukan untuk hari, ruangan, atau orang yang belum dilihat.
3. **Penghalusan terpusat melihat masa depan.** Sah untuk analisis offline; sistem
   real-time perlu penghalusan kausal dan akurasinya akan sedikit turun.

Langkah lanjutan yang paling menaikkan nilai: **sesi kedua di hari berbeda**, lalu latih
pada sesi 1 dan uji pada sesi 2.

## Kaitan dengan folder induk

- `../tools/localize_baseline.py` — aturan `argmax` tangan (79,4%), pembanding di Bagian 3.
  Notebook menjalankan skrip itu langsung, bukan mengimplementasikan ulang.
- `../LOCALIZATION_RUNBOOK.md` — prosedur capture kalau data perlu diambil ulang.
- `../KNOWLEDGE.md` — format frame dan catatan sistem pengumpulan data.
