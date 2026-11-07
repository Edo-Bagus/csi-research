# ml_people_count — menghitung orang dari CSI

EDA dua dataset counting di **dua ruang kelas berbeda**: `data-14-9`
(14 September 2026, 10 sesi, kelas 7–16 orang) dan `data-15-9` (15 September
2026, 9 sesi, kelas 45–72 orang).

**Hasil utama:** okupansi menambah variance CSI yang **berstruktur waktu**, dan
itu memisahkan kosong dari berpenghuni **tanpa tumpang-tindih** di 19 sesi dua
ruangan. Penghitungan jumlah orang dan per zona **tidak** terjawab, dan alasannya
struktural. Langsung ke "HASIL UTAMA" di bawah.

> **KEDUA dataset diambil di KELAS YANG SEDANG BERLANGSUNG** (ruangan 1:
> 12:50–15:19 tanggal 14-9; ruangan 2: 12:36–14:28 tanggal 15-9). Subjeknya
> mahasiswa yang sedang kuliah, **bukan relawan yang bisa disuruh berdiri di
> posisi tertentu**. Banyak hal yang tampak seperti cacat data sebenarnya rekaman
> yang benar dari apa yang terjadi — okupansi konstan karena mahasiswa duduk dan
> tetap duduk; tidak ada kelas setengah penuh karena kelas tidak pernah terisi
> separuh. Lihat `KNOWLEDGE.md` §12.1 dan §13.

Sesi kosong: `count_s10` (ruangan 1, 290 detik, direkam setelah kelas bubar) dan
`count_2_9` (ruangan 2, ~350 detik, 90% span di total=0). Satu per ruangan —
keduanya membuka perbandingan kosong-vs-berpenghuni, dan keduanya juga jadi
caveat terbesar yang tersisa (n=2).

## Tata letak

```
ml_people_count/
├── pyproject.toml            paket + versi dependensi
├── requirements.txt          versi PERSIS yang menghasilkan angka di README ini
├── Makefile                  `make all`, `make test`
├── src/csi_occupancy/        paket analisis
│   ├── paths.py              satu-satunya tempat yang tahu lokasi file
│   ├── datasets.py           Dataset per ruangan, baca .bin, label, fitur jendela
│   ├── coherence.py          HASIL UTAMA: koherensi temporal
│   ├── session_level.py      tingkat sesi kedua ruangan, fitur flux
│   └── eda_windows.py        EDA per jendela + kontrol null (ruangan 2)
├── data/
│   ├── raw/data-14-9/        ruangan 1: 10 sesi × (3–4 .bin + 2 CSV label)
│   ├── raw/data-15-9/        ruangan 2: 9 sesi × (4 .bin + 2 CSV label)
│   └── processed/            cache fitur, boleh dihapus kapan saja
├── results/
│   ├── tables/               CSV hasil analisis
│   └── figures/              gambar
├── notebooks/                notebook ruangan 1 (historis) + sumbernya
└── tests/                    25 tes, menjaga kegagalan yang SENYAP
```

Tiga aturan yang membentuk tata letak ini:

1. **`data/raw/` hanya dibaca, tidak pernah ditulis.** Data mentah 1.4 GB tidak
   bisa dibuat ulang; apa pun yang dihasilkan analisis masuk `data/processed/`
   atau `results/`. Tidak ada skrip yang menulis ke `data/raw/`.
2. **Tidak ada `sys.path` di skrip analisis.** Semuanya mengimpor paket. Satu
   `sys.path.insert` yang tersisa ada di `datasets.py` untuk `read_bin` dari
   `../tools/`, dan sengaja dipusatkan di situ.
3. **Jalur berasal dari `paths.py`, bukan dari `os.getcwd()`.** Jadi skrip bisa
   dijalankan dari direktori mana pun.

## Menjalankan

Sekali di awal:

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2\ml_people_count
python -m pip install -e ".[dev]"
```

Analisis (tidak butuh Jupyter):

```powershell
python -m csi_occupancy.coherence        # HASIL UTAMA: koherensi temporal
python -m csi_occupancy.session_level    # tingkat sesi, kedua ruangan
python -m csi_occupancy.eda_windows      # EDA ruangan 2 + kontrol null
```

Atau `make all` / `make coherence`. Jalanan pertama membaca 1.4 GB `.bin` dan
butuh beberapa menit; hasilnya di-cache ke `data/processed/`, jalanan berikutnya
jauh lebih cepat. Hapus cache dengan `make clean`.

Tes:

```powershell
python -m pytest tests\ -v                      # semua (butuh data/raw/)
python -m pytest tests\ -v -m "not needs_data"  # tanpa data mentah
```

`datasets.py` mengimpor `read_bin` dari `../tools/csi_merge.py` — **jangan salin
definisi struct-nya**, format frame tidak punya version field dan mismatch-nya
gagal diam-diam.

### Kenapa ada tes di proyek analisis

Semua kesalahan yang pernah nyata di proyek ini **tidak memunculkan error**: denah
zona tertukar antar ruangan, board mati yang memotong 97% sesi, label yang diisi 0
padahal "tidak tercatat", baseline ruangan lain yang bocor lewat cache. Tes di
`tests/` menjaga tiap kasus itu.

`tests/test_null_controls.py` menguji **kontrol null-nya sendiri**: diberi sinyal
palsu ia harus lolos, diberi sinyal nyata ia harus menolak. Tanpa itu, "null-nya
tidak terlampaui" bisa berarti tidak ada sinyal **atau** kontrolnya rusak — dan
seluruh kesimpulan negatif proyek ini bergantung pada bedanya.

## Notebook (historis)

`notebooks/eda_people_count.ipynb` mencakup **ruangan 1 saja** dan **mendahului**
temuan koherensi. Disimpan sebagai rekaman kerja awal; untuk hasil yang berlaku,
baca bagian HASIL UTAMA di bawah dan jalankan skripnya.

Notebook ditulis lewat `nb_cells.py` supaya bisa di-review sebagai teks biasa
(diff `.ipynb` tidak terbaca manusia). Untuk mengubahnya: edit
`notebooks/nb_cells.py`, jalankan `make notebook`, lalu eksekusi ulang.

> Dua jebakan saat menulis `nb_cells.py`: isi sel berupa string `r"""..."""`,
> jadi docstring `"""` di dalam sel kode menutup sel itu lebih awal — pakai
> komentar `#`. Dan tiap baris sumber harus tetap berakhiran newline, kalau tidak
> seluruh sel menyatu jadi satu baris saat dieksekusi.

## Reproduksibilitas

`requirements.txt` memuat versi **persis** yang menghasilkan setiap angka di
dokumen ini (Python 3.12.2, numpy 2.3.5, pandas 2.3.3, scipy 1.16.3,
scikit-learn 1.8.0). Semua analisis memakai `random_state`/seed tetap, jadi
angkanya deterministik.

Kalau suatu angka di README tidak lagi cocok dengan keluaran skrip, itu bug —
bukan variasi acak. Jalankan `make test` lebih dulu.

## Dua dataset = dua ruangan

`data-14-9` dan `data-15-9` direkam di **ruang kelas yang berbeda**, bukan dua
sampel ruangan yang sama. Tiap dataset punya objek `loader.Dataset` sendiri:

```python
import loader
loader.DS_14_9     # ruangan 1: A=d0 B=bf C=38 D=4b, kosong=count_s10
loader.DS_15_9     # ruangan 2: A=d0 B=bf C=4b D=38, kosong=count_2_9
f = loader.window_features("count_2_4", ds=loader.DS_15_9)
```

Denah zona **berbeda** antar ruangan (C dan D tertukar). Denah itu ikut di objek
`Dataset`, bukan konstanta global yang diedit manual, karena denah yang usang
menghasilkan angka zona salah **tanpa error apa pun**. Default tetap `DS_14_9`
supaya notebook lama jalan tanpa diubah.

Fitur CSI dari dua ruangan **tidak boleh digabung** jadi satu set latih — itu
mencampur efek ruangan dengan efek jumlah orang. Klaim yang didukung adalah
**replikasi**: hasil dilaporkan per ruangan.

## HASIL UTAMA: okupansi menambah variance yang BERSTRUKTUR WAKTU

> Temuan terkuat dan paling bisa ditafsirkan dari kedua dataset. Skrip:
> `csi_occupancy/coherence.py` (`python -m csi_occupancy.coherence`). Ini yang
> sebaiknya jadi hasil utama skripsi.

Diukur sebagai autokorelasi lag-k amplitudo per subcarrier (dirata-rata atas
subcarrier aktif, hanya jendela plateau):

| Lag | r1 kosong | r1 N=16 | r2 kosong | r2 N=72 |
|---|---|---|---|---|
| 1 paket | +0.07 | +0.56 | +0.16 | +0.68 |
| ~1 s (40 pkt) | +0.06 | **+0.40** | +0.02 | **+0.51** |
| ~5 s (200 pkt) | +0.02 | +0.24 | +0.01 | +0.35 |
| ~20 s (800 pkt) | +0.01 | +0.05 | −0.00 | +0.21 |

**Ruangan kosong kehilangan korelasi dalam 1–2 paket lalu datar** — variasinya
bebas antar-sampel, yaitu derau penerima/termal. **Ruangan berpenghuni bertahan
berkorelasi ratusan paket** — variasinya proses fisik dengan skala waktunya
sendiri: tubuh bergeser, bergerak, bernapas.

Koherensi@1s di **19 sesi, TANPA tumpang-tindih**:

- 17 sesi berpenghuni: **0.356 – 0.572** (mean 0.495)
- 2 sesi kosong: **0.146** (`count_s10`) dan **0.052** (`count_2_9`)
- rasio **5.0x**; kosong maksimum (0.146) < berpenghuni minimum (0.356)
- Mann-Whitney **p=0.0058**, dan berlaku di kedua ruangan secara independen

### Kenapa ini menjelaskan temuan-temuan lama

`sub_var` (variance biasa) lemah dan `amp_mean` nyaris buta — sejalan dengan
temuan lokalisasi lama (variance 79% vs amplitudo 36%). Sebabnya sekarang jelas:
**variance saja tidak bisa membedakan derau dari struktur.** Ruangan kosong dan
berpenghuni punya variance sebanding; yang membedakan adalah apakah variance itu
punya SKALA WAKTU.

### Artefak yang sudah disingkirkan

- **Bukan laju paket.** 31–43 Hz di semua sesi, jadi 40 paket ≈ 1 s di semuanya.
- **Bukan SNR / noise floor.** **14 dari 17** sesi berpenghuni RSSI-nya LEBIH
  LEMAH daripada sesi kosong, tapi koherensinya tetap 0.356–0.572 (3–8x lebih
  tinggi). Amplitudo rata-rata setara (20.4 kosong vs 19.9 berpenghuni).
- **Nyaris bebas confound jam.** corr(koherensi, jam) = +0.25 dan −0.45 — kontrol
  yang mematikan SEMUA fitur level, dan koherensi lolos.

### Batasnya

- **Bukan penghitungan.** Di antara sesi berpenghuni saja, koherensi vs jumlah
  orang rho=+0.16 (r1) dan −0.22 (r2), keduanya tidak signifikan. Kehadiran
  terdeteksi, jumlah orang tidak.
- **Hanya 2 sesi kosong**, satu per ruangan, masing-masing direkam di waktu
  berbeda dari sesi berpenghuni ruangan itu. Pemisahan tanpa tumpang-tindih dan
  argumen mekanismenya kuat, tapi sampel kosong tetap n=2.

## Arah kedua: laju fluktuasi vs ukuran kerumunan (SUGESTIF)

Fitur **dinamika** (`flux` = mean|selisih 1 langkah| / mean level, langkah ~1 s).
Karena berupa selisih, drift skala jam hilang dengan sendirinya. Skrip:
`csi_occupancy/session_level.py`.

- **16 dari 18** korelasi flux-vs-N bertanda POSITIF di kedua ruangan, binomial
  **p=0.0007**. Makin ramai, makin cepat CSI berfluktuasi — prediksi berarah,
  bukan sekadar "ada korelasi".
- `38_rssi_mean_flux` (+0.70/+0.66) dan `38_sub_var_flux` (+0.54/+0.59) replikasi
  lintas ruangan dengan tanda sama; permutation p=0.0105.
- **Caveat:** partial correlation terhadap jam lolos di ruangan 1 (+0.63, +0.65,
  +0.58) tapi **negatif** di ruangan 2. Jadi **sugestif, belum tuntas.**

Tingkat sesi adalah unit yang benar-benar disampel baik oleh kedua dataset: 19
sesi, N = 0..72. Ruangan 1 mengisi ujung sepi (0–16), ruangan 2 ujung padat
(45–72). Sendiri-sendiri rentangnya sempit; digabung jadi nyata.

**Fitur LEVEL per sesi (median amp/rssi/var) DIBUANG.** Tampak sangat kuat
(`4b_sub_std_spatial` rho −0.92 / −0.90, replikasi lintas ruangan, permutation
p=0.0025) tapi `corr(jam, N)` = +0.98 dan +0.83, dan setelah jam di-partial-out
rho jatuh ke **−0.36 / −0.31**. Tidak bisa dibedakan dari drift kanal sepanjang
siang. Jangan dilaporkan sebagai penginderaan okupansi.

## Tidak ada satu board yang jadi "sensornya"

Respons board tidak konsisten antar ruangan: `4b` terkuat di ruangan 1 (rho
+0.85), `bf` di ruangan 2 (+0.73), dan `d0` **berbalik tanda** (+0.65 → −0.51).
Digabung dengan hasil permutasi zona di bawah: CSI di sini membawa informasi
okupansi **tingkat ruangan**, bukan informasi **spasial** yang bisa dipercaya.
Klaim per-board tidak akan replikasi; klaim agregat-antar-board replikasi.

## Ringkasan temuan data-15-9 (ruangan 2)

Dataset ini jauh lebih baik secara teknis: 9 sesi, **keempat board utuh di
semuanya**, 5068 jendela terpakai, kelas 52–72 orang, dan label yang benar-benar
berubah terhadap waktu (tidak seperti 14-9). Meski begitu, **tak satu pun dari
tiga pertanyaan riset terjawab**, dan alasannya sama untuk ketiganya.

**Semua hasil di bawah awalnya tampak POSITIF** dengan ukuran biasa (effect size,
akurasi, MAE vs baseline) dan runtuh di bawah kontrol null. Kontrol itulah
temuan metodologisnya.

*1. Deteksi okupansi lewat fitur LEVEL — MASIH CONFOUNDED.*
(Deteksi yang BERHASIL ada di "HASIL UTAMA" di atas, lewat struktur waktu —
bukan lewat effect size fitur level di bawah ini.)

- Effect size kosong-vs-terisi besar: `bf_sub_var` d=**+2.00**, `4b_sub_var`
  d=+1.93 — konsisten dengan temuan lama bahwa variance mengalahkan amplitudo.
- Tapi LOSO akurasi **0.933 = persis proporsi kelas mayoritas**, dan `count_2_9`
  (satu-satunya sesi dengan jendela kosong) dapat akurasi **0.000**. Model
  menebak "terisi" untuk semua jendela dan tetap dapat 93%.
- Sebabnya struktural: **316 dari 336** jendela kosong berasal dari `count_2_9`
  saja; sesi lain hanya menyumbang 1–11 jendela di detik-detik awalnya. Jadi
  "kosong" praktis identik dengan "sesi pukul 14:22" — sama persis dengan cacat
  `count_s10` di ruangan 1.

*2. Berapa banyak orang — TETAP BELUM TERJAWAB.*

- Antar-sesi: RF MAE **8.09** orang vs baseline rata-rata **9.37** (sd label 10.7).
- Dalam sesi, diuji lawan **null label-digeser-sirkuler** (distribusi dan
  autokorelasi label dipertahankan, kaitan ke CSI dihancurkan): `count_2_1`
  tampak terbaik (MAE 4.10 vs baseline 5.69) tapi null-nya justru **lebih mudah**
  diprediksi (3.64). Jadi itu autokorelasi, bukan penginderaan.
- Sesi yang lolos null ternyata yang labelnya **datar**: seluruh variasinya ada di
  ~120 detik pertama (sd 7.7–11.5) lalu plateau (sd 0.5–1.4). Model belajar
  membedakan "menit pertama" dari "sisa sesi", bukan menghitung orang.
- Setelah 120 detik awal dibuang, hanya **2 dari 5** sesi mengalahkan null-nya,
  pada label yang nyaris tak bergerak (sd 1.4–2.5 orang).

*3. Zona mana yang terisi — TETAP BELUM TERJAWAB.*

- Okupansi zona kini seimbang (A=21.8, C=19.4, D=18.7 rata-rata) — masalah "zona B
  selalu kosong" di ruangan 1 tidak terulang.
- Tapi diuji lawan **seluruh 24 permutasi** zona→board, denah pengguna ada di
  peringkat **8/24, 4/24, 3/24, 20/24** tergantung statistik. Tidak ada pemenang
  konsisten. Permutasi terbaik untuk `rssi_std` justru denah **14-9**, yang salah
  untuk ruangan ini.
- Zona juga naik bersamaan saat ruangan terisi (`corr(C, total)`=+0.85), jadi
  korelasi board-zona sebagian besar hanyalah confound jumlah total.

*Yang membaik dibanding ruangan 1:* akurasi menebak sesi turun dari **96.6% → 71.7%**,
jadi sidik jari per-sesi lebih lemah di sini. Keempat board juga utuh di semua sesi.

### Kesimpulan: yang menghambat adalah PROTOKOL, bukan model

Kedua dataset gagal karena sebab yang sama: **satu sesi = satu tingkat okupansi
yang nyaris konstan**, sehingga "kosong vs terisi" dan "N vs M orang" selalu jadi
perbandingan *antar-sesi*, tak terpisahkan dari waktu, drift kanal, dan identitas
sesi. Tidak ada model yang bisa memperbaiki ini. Lihat "Langkah berikutnya" —
butir 1 persis obatnya, dan biayanya hanya satu perekaman.

## Ringkasan temuan data-14-9 (ruangan 1)

**Yang sehat.** 39 `.bin` terbaca utuh, seluruhnya `sig_len=114`, ~36–44 paket/detik
per board, 256 subcarrier (244 aktif) per paket. Pelabelan presisi milidetik.
Ada baseline ruangan kosong (`count_s10`).

**Dua pertanyaan, dua jawaban berbeda.**

*1. Kosong vs berpenghuni — TERBEDAKAN, tapi lewat uji yang belum dikontrol.*

> Angka di bawah belum melalui kontrol kelas-mayoritas maupun kontrol jam. Yang
> bertahan setelah kontrol itu adalah koherensi temporal ("HASIL UTAMA" di atas).
> Effect size di bawah tetap benar sebagai deskripsi, tapi jangan dikutip sebagai
> bukti deteksi tanpa menyebut kontrolnya.

- 12 dari 24 fitur punya |Cohen's d| > 0.8; 7 fitur > 1.5.
- Terkuat `bf_rssi_mean` (d = −6.1), `d0_amp_mean` (d = −3.0),
  `4b_sub_std_spatial` (d = −3.0).
- **10 dari 24 fitur** bernilai di luar rentang SELURUH sembilan sesi
  berpenghuni — jadi ini bukan sekadar hanyutan kanal. `bf_rssi_mean` berada
  7.0 SD dari rata-rata sesi berpenghuni.

*2. Berapa banyak orang — BELUM TERJAWAB.*

- Random forest menebak **sesi** dari fitur CSI dengan akurasi **96.6%** (acak 10%).
- Median |korelasi| fitur terhadap jumlah orang turun **0.288 → 0.036** begitu
  efek sesi dibuang; 18 dari 24 fitur kehilangan >50% korelasinya.
- Uji respons di transisi label vs waktu acak: **5 dari 18** kombinasi signifikan.
  Terkuat `rssi_std`. Ukuran *level* (`amp_mean`) tetap tidak pernah signifikan.

*3. Zona mana yang terisi — BELUM TERJAWAB.*

- Denah board (dikonfirmasi pengguna): A=`d0`, B=`bf`, C=`38`, D=`4b`.
- Kopling board-zona **tidak terdeteksi**: semua korelasi |r| < 0.20, dan
  pasangan yang cocok menurut denah lebih kuat hanya di 3 dari 6 statistik
  (setara lempar koin).
- Sebabnya: isi tiap zona nyaris tak berubah dalam satu sesi. Zona B bahkan
  hampir tak pernah terisi (rata-rata 0.11 orang di seluruh sesi berpenghuni;
  A=1.86, C=4.77, D=6.21).

> Denah ini **berbeda** dari `COUNTING_RUNBOOK.md`, yang menukar A dan C
> (runbook: A=`38`, C=`d0`). Yang dipakai adalah angka pengguna. Data tidak
> bisa menengahi — selisihnya jauh di bawah derau. Kalau ternyata runbook yang
> benar, ubah `zone_board` pada `DS_14_9` di `src/csi_occupancy/datasets.py` lalu jalankan ulang
> notebook. (Di data-15-9 uji 24 permutasi juga tidak bisa menengahi — lihat atas.)

**Kesimpulan (ruangan 1 saja).** Data ini mendukung **deteksi okupansi**, tapi
bukti yang bertahan setelah kontrol adalah **koherensi temporal**, bukan effect
size fitur level di atas — lihat "HASIL UTAMA". Data ini **belum** mendukung
**penghitungan** jumlah orang maupun per zona: label melompat dari 0 langsung ke
7–16, dan isi zona nyaris tak berubah dalam satu sesi.

Penyebab kegagalan (2) dan (3) sama, dan itu sifat ruang kelas, bukan cacat
metode: mahasiswa duduk dan tetap duduk, jadi tidak ada variasi untuk
dikorelasikan.

### Framing untuk skripsi (berlaku, per 2026-09-19)

Pertanyaan riset: *bisakah CSI WiFi komoditas mendeteksi okupansi ruang kelas
nyata yang sedang dipakai, tanpa mengendalikan penghuninya?* Ini penginderaan
oportunistik di lingkungan tak terkendali — setting yang lebih sulit, bukan versi
gagal dari studi laboratorium.

Dua kontribusi, keduanya didukung data yang ada:

1. **Metodologis (paling kokoh).** Penginderaan okupansi CSI komoditas di ruangan
   tak terkendali didominasi confound yang disembunyikan evaluasi standar.
   Buktinya semuanya dari data sendiri: classifier sesi 96.6%, detektor yang
   persis menyamai kelas mayoritas sementara satu-satunya sesi kosongnya dapat
   0.000, null label-digeser yang mengalahkan label asli, denah zona yang cuma
   peringkat 8/24, dan korelasi kuat yang lenyap setelah kontrol jam.
2. **Empiris — deteksi lewat struktur waktu.** Lihat "HASIL UTAMA": pemisahan
   tanpa tumpang-tindih di 19 sesi dua ruangan, mekanisme yang bisa dijelaskan,
   artefak sudah disingkirkan. Sertakan caveat n=2 sesi kosong.

- **Laporkan terbuka berikut alasannya:** penghitungan jumlah orang dan per zona.
  Arah flux ditulis sebagai sugestif, bukan hasil.
- **Angka 96.6% itu bahan tulisan, bukan aib.** Banyak literatur mengevaluasi
  dengan pembagian acak per jendela lalu melaporkan akurasi menggelembung;
  kemampuan menebak *sesi* sebesar 96.6% adalah bukti konkret kenapa evaluasi
  seperti itu tidak sah.
- **Aturan yang tidak bisa ditawar:** jangan pernah membagi train/test acak per
  jendela. Selalu pakai sesi sebagai grup.

## Langkah berikutnya, berurutan

> Semua di bawah bisa dilakukan **tanpa mengatur siapa pun** — itu syaratnya,
> karena subjeknya kelas nyata. Saran seperti "tahan 60 detik di tiap tingkat"
> atau "satu orang berjalan sendiri" TIDAK berlaku di sini.

1. **Rekam 10 menit SEBELUM kelas mulai dan 10 menit SESUDAH bubar, TANPA
   memutus perekaman.** Kelas punya transisi okupansi alami: mahasiswa datang
   bertahap lalu pergi bertahap. Ini memberi ramp 0→N dan N→0 yang sesungguhnya —
   "tangga" yang diberikan jadwal kuliah, bukan instruksi.

   **Setelah EDA data-15-9, ini bukan lagi sekadar "paling berharga" — ini
   satu-satunya yang membuka ketiga pertanyaan riset.** Yang dibutuhkan adalah
   kosong DAN terisi di DALAM satu rekaman utuh. Selama keduanya selalu di sesi
   berbeda, "kosong vs terisi" tak bisa dipisahkan dari "sesi A vs sesi B", dan
   tak ada model yang bisa menambalnya. Biayanya satu perekaman; kalau baru
   disadari setelah pengumpulan, yang hangus satu hari penuh.
2. **Lebih banyak sesi ruangan kosong** di waktu dan hari berbeda (sebelum kelas,
   sesudah kelas, jam istirahat, hari tanpa jadwal). Satu-satunya kondisi yang
   sepenuhnya bisa dikendalikan; langsung memperkuat hasil utama.
3. **Kelas dengan ukuran berbeda** (seminar 5 orang vs kuliah 30 orang) — variasi
   jumlah orang antar sesi tanpa mengatur siapa pun.
4. **Pastikan keempat board terlihat sebelum mulai.** (Di data-15-9 sudah
   tercapai: 4 board utuh di 9 dari 9 sesi.)
5. **Zona: biarkan atau ambil gratis.** Kalau mahasiswa selalu duduk di C dan D,
   counting per zona memang tak terjawab di ruangan ini — tulis sebagai temuan
   tentang ruangannya.

> Periode datang/pergi berarti orang **bergerak**, yang mempengaruhi CSI berbeda
> dari orang **duduk**. Perlakukan sebagai dua tugas terkait, bukan derau.

## Normalisasi

`loader.window_features(..., normalize=..., ds=...)` menerima `"none"`,
`"session"`, dan `"empty"`. Yang terakhir memakai sesi kosong **dataset yang
dipakai** (`count_s10` untuk ruangan 1, `count_2_9` untuk ruangan 2): tiap fitur
dinyatakan relatif terhadap statistik board itu sendiri saat ruangan kosong
(median/MAD). Ini yang disebut wajib di `ml_localization/features.py`.

Perlakukan hasilnya sebagai indikatif selama tiap ruangan masih punya satu sesi
kosong saja. Cache baseline di-key pada **nama dataset**, jadi baseline ruangan 1
tidak bisa lagi bocor ke ruangan 2 — itu pernah mungkin ketika key-nya `data_dir`.

> Catat: hasil utama (koherensi temporal) **tidak** memakai `normalize` sama
> sekali. Koherensi adalah autokorelasi, jadi sudah bebas skala per board dengan
> sendirinya — salah satu alasan ia lolos kontrol yang mematikan fitur level.
