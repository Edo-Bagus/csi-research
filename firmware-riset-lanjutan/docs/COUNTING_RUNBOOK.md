# RUNBOOK — Capture people counting per zona (dipakai saat OFFLINE)

Prosedur pengambilan data untuk tugas **menghitung jumlah orang per zona A/B/C/D**.
Semua perintah bisa disalin apa adanya. Tidak butuh internet.

Baca `RUNBOOK.md` dulu untuk prosedur dasar (pindah jaringan, cek IP, flash board).
Dokumen ini hanya menambahkan bagian khusus counting.

---

## Denah zona

Router di TENGAH ruangan, empat zona = empat kuadran. Board di tiap sudut.

```
              9 m
    A ---------------------- B        A = kiri-atas   (board d0)
    |                        |        B = kanan-atas  (board bf)
    |           R            |  7 m   C = kiri-bawah  (board 38)
    |       (router)         |        D = kanan-bawah (board 4b)
    |                        |
    C ---------------------- D
```

> **PENTING — denah di atas berlaku untuk RUANGAN 1 (`data-14-9`) saja.**
> Denah zona **berbeda per ruangan**, jadi jangan menyalin diagram di atas ke
> pengambilan data di ruangan lain tanpa mengukur ulang.
>
> | Zona | Ruangan 1 (`data-14-9`) | Ruangan 2 (`data-15-9`) |
> |---|---|---|
> | A | `d0` | `d0` |
> | B | `bf` | `bf` |
> | C | `38` | **`4b`** |
> | D | `4b` | **`38`** |
>
> **Catat denah zona→board di catatan sesi SETIAP KALI mulai di ruangan baru.**
> Frame `.bin` tidak punya version field dan nama file hanya memuat `node_id`,
> jadi denah yang salah menghasilkan angka zona yang salah **tanpa pesan error
> apa pun** — tidak ada yang bisa menangkapnya dari data belakangan.
>
> Sumber kebenaran yang dipakai kode: `loader.DS_14_9.zone_board` dan
> `loader.DS_15_9.zone_board` di `ml_people_count/loader.py`. Untuk dataset baru,
> tambahkan objek `Dataset` baru di sana — jangan mengedit denah yang sudah ada.
>
> *Dikoreksi 2026-09-14:* versi awal dokumen ini menulis A=`38`, C=`d0` untuk
> ruangan 1 — tertukar. *Diperbarui 2026-09-19:* ditambahkan denah ruangan 2.

> **Denah zona tidak bisa diverifikasi dari data.** Diuji lawan seluruh 24
> permutasi zona→board di `data-15-9`, denah pengguna hanya peringkat 8/24,
> 4/24, 3/24, dan 20/24 tergantung statistik yang dipakai — setara kebetulan.
> Jadi pengukuran fisik di lapangan adalah SATU-SATUNYA sumber kebenaran; data
> tidak akan pernah bisa menengahi kalau catatannya hilang.

> **Yang sebenarnya diukur.** Tiap board mengukur kanal `router -> board`. Orang
> mempengaruhi sebuah board saat berada di sekitar garis itu. Jadi "zona" di sini
> adalah sektor arah dari router, bukan kotak geometris yang tegas. Orang yang
> berdiri tepat di perbatasan A/B akan mempengaruhi keduanya — itu batas metode,
> bukan kesalahan pencatatan. Tulis apa adanya di skripsi.

Tandai keempat batas zona di lantai dengan lakban **sebelum mulai**. Kalau orang
tidak tahu persis di mana batasnya, label yang kamu catat tidak akan cocok dengan
apa yang dirasakan board.

---

## Yang dibutuhkan

- 4 board sudah ter-flash firmware v2, tergantung di sudut, **tinggi seragam** (mis. 1 m)
- Router di tengah, **tidak dipindah sama sekali** sampai semua sesi selesai
- Laptop di `<SSID>`, IP harus **<IP_LAPTOP>**
- **Dua terminal**: #1 kolektor, #2 pencatat label
- Orang-orang yang akan jadi subjek (lihat rencana sesi di bawah)

> Kalau router bergeser di tengah jalan, semua sesi sebelumnya tidak bisa
> digabung dengan sesudahnya. Ulangi dari awal.

---

## Langkah 0 — Cek IP (sekali di awal)

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2
ipconfig | findstr /i "IPv4 Gateway"
```

Harus `<IP_LAPTOP>`. Kalau bukan, **berhenti** — baca `RUNBOOK.md` Langkah 1.

---

## Langkah 1 — Kolektor DULU (terminal #1)

**SATU SESI = SATU FOLDER.** Ganti nama folder tiap sesi.

```powershell
python tools\csi_collector.py --outdir capture\count_s01_kosong --duration 180 -v
```

Tunggu sampai muncul `Kolektor siap`. **Baru** nyalakan/reset keempat board
bersamaan. Tunggu keempatnya muncul di kolektor:

```
[192.168.50.xxx] node_id=0x38 mac=... -> capture\count_s01_kosong\node38_....bin
[192.168.50.xxx] node_id=0xbf ...
[192.168.50.xxx] node_id=0xd0 ...
[192.168.50.xxx] node_id=0x4b ...
```

**Jangan mulai sebelum keempatnya terlihat.** Kalau cuma tiga, hentikan, hapus
folder, ulangi — bin tanpa node lengkap akan terbuang saat merge.

---

## Langkah 2 — Pencatat label (terminal #2)

Jalankan **sebelum orang mulai masuk ruangan**:

```powershell
python tools\mark_occupancy.py --outdir capture\count_s01_kosong
```

Folder harus **sama persis** dengan `--outdir` kolektor.

Tombol:

| Tombol | Aksi |
|---|---|
| `a` `b` `c` `d` | **tambah** 1 orang di zona itu |
| `A` `B` `C` `D` (Shift) | **kurangi** 1 orang |
| `1` `2` `3` `4` | set zona A/B/C/D ke nol |
| `0` | kosongkan SEMUA zona |
| `z` | undo penekanan terakhir |
| `p` | cetak keadaan sekarang (tidak mengubah apa pun) |
| `q` | selesai dan tulis file |

Menekan `a` dua kali = **dua orang masuk zona A**, bukan batal. Untuk mengurangi
pakai Shift.

> **Tekan TEPAT saat orang melewati batas zona**, bukan setelah dia berhenti
> berjalan. Waktu yang tercatat adalah waktu penekanan.

Kalau ruangan sudah ada orang saat kolektor mulai:

```powershell
python tools\mark_occupancy.py --outdir capture\count_s01_kosong --initial A=2,B=1
```

---

## Langkah 3 — Selesai

Urutan berhenti: **kolektor dulu berhenti** (atau Ctrl-C), **lalu** `q` di pencatat
label. Kalau pencatat berhenti duluan, bin-bin terakhir tidak punya label dan akan
terbuang.

Pencatat akan mencetak sebaran waktu per jumlah orang. **Lihat angka ini sebelum
lanjut sesi berikutnya** — kalau satu kelas hampir tidak muncul, ulangi/tambah sesi
sekarang, bukan setelah semua data terkumpul.

---

## Langkah 4 — Cek hasil (segera, jangan ditunda)

```powershell
python tools\csi_merge.py capture\count_s01_kosong --stats-only --bin-ms 100
```

Yang dilihat:

| Cek | Harus |
|---|---|
| Node | **4** |
| pkt/s per node | **~35-42** (lihat catatan di bawah) |
| bin berisi semua node | **>90%** |
| `hilang` | kecil |

Kalau coverage di bawah ~90%, sesi itu lemah. **Ulangi sekarang** selagi setup
masih berdiri — jauh lebih murah daripada menyadarinya seminggu kemudian.

### Catatan rate: yang benar ~40 pkt/s, bukan ~10

`RUNBOOK.md` menulis "~10 pkt/s" dan komentar `PING_INTERVAL_MS` di firmware juga
bilang "100 ms -> ~10 paket/detik". **Angka itu keliru** — terukur dari capture
nyata 2026-09-09:

| Sesi | Rate per node |
|---|---|
| `loc_walk` | 35.5 - 41.4 pkt/s |
| `loc_baseline` | 37.2 - 40.7 pkt/s |
| `loc_static` | ~41.7 pkt/s |
| `sesi4` | ~10 pkt/s (outlier) |

Ping 100 ms hanya **memicu** lalu lintas; yang terekam adalah SEMUA frame
`sig_len=114` dari router (`ap_mac` sama, channel 11), dan router membalas lebih
sering daripada satu balasan per ping. Strukturnya berkelompok: 33% paket datang
<5 ms setelah paket sebelumnya, ~27 burst/detik.

Jadi kalau kolektor menunjukkan ~40 pkt/s, **itu normal** — jangan dikira bug.
Yang justru perlu dicurigai adalah kalau turun ke ~10 pkt/s.

> **Untuk skripsi:** sampling rate CSI efektif **bukan** 10 Hz konstan, melainkan
> ~40 paket/detik dengan jarak antar-paket tidak seragam (median ~20 ms, p10 ~0.5 ms,
> p90 ~63 ms). Karena itu binning 100 ms dipakai: bin memberi laju seragam 10 Hz
> yang tidak dimiliki data mentah. Tulis begini, jangan mengklaim "sampling rate 10 Hz".

---

## Rencana sesi

> **PENTING — rencana di bawah mengandaikan subjek yang bisa diarahkan.**
> Dataset `data-14-9` (2026-09-14) TIDAK diambil begitu: itu kelas yang sedang
> berlangsung, subjeknya mahasiswa yang sedang kuliah. Instruksi seperti "diam
> 45 detik di tiap zona" tidak bisa dijalankan di situasi seperti itu.
>
> Kalau pengambilan datamu juga di kelas nyata, lewati tabel di bawah dan pakai
> `KNOWLEDGE.md` §12.6 — daftar tindakan yang tidak butuh kendali atas orang.
> Yang paling berharga di sana: **rekam 10 menit sebelum kelas mulai dan 10 menit
> sesudah bubar**, supaya ramp okupansi 0→N dan N→0 yang alami ikut terekam.

Jangan ambil satu sesi panjang. Ambil banyak sesi pendek dengan kondisi berbeda —
model yang dilatih dari satu sesi panjang akan menghafal kondisi hari itu.

### Wajib

| Folder | Isi | Durasi |
|---|---|---|
| `count_s01_kosong` | Ruangan KOSONG, tidak ada orang sama sekali | 3 menit |
| `count_s02_1org_diam` | 1 orang, diam 45 s di tiap zona: A→B→C→D | 3 menit |
| `count_s03_2org_diam` | 2 orang, kombinasi zona berbeda tiap 45 s | 4 menit |
| `count_s04_3org_diam` | 3 orang, kombinasi zona berbeda tiap 45 s | 4 menit |
| `count_s05_4org_diam` | 4 orang, satu per zona, lalu ditumpuk | 4 menit |
| `count_s06_dinamis` | Orang masuk/keluar/pindah zona bebas | 6 menit |
| `count_s07_dinamis2` | Ulangi s06, urutan berbeda | 6 menit |

`count_s01_kosong` adalah **baseline** dan paling mudah dirusak — satu orang lewat
di depan pintu sudah cukup. Keluar ruangan, tutup pintu, biarkan berjalan sendiri.

Untuk sesi diam (`s02`–`s05`), pakai stopwatch dan berpindah secepatnya antar
posisi. Tekan tombol tepat saat orang melewati batas.

### Kalau sempat, tambahan yang bikin model jauh lebih kuat

- Ulangi `s02`–`s05` dengan **orang yang berbeda** (tinggi/postur berbeda)
- Satu set sesi di **hari lain** — ini yang paling menentukan apakah model bisa
  digeneralisasi atau cuma menghafal
- Sesi dengan orang **duduk**, bukan berdiri

> **Kenapa hari lain itu penting.** Kalau semua data dari satu hari, akurasi tinggi
> yang kamu dapat sebagian berasal dari kondisi kanal yang tidak berubah — bukan dari
> jumlah orang. Cara satu-satunya untuk tahu adalah menguji dengan data hari lain.

---

## Langkah 5 — Gabung dan beri label (bisa nanti, tidak harus di lokasi)

Per sesi:

```powershell
python tools\csi_merge.py capture\count_s01_kosong -o count_s01.csv --bin-ms 100
python tools\label_occupancy.py count_s01.csv --occupancy capture\count_s01_kosong\occupancy.csv -o count_s01_labeled.csv
```

`label_occupancy.py` menambah kolom `A,B,C,D,total` ke tiap bin, lalu mencetak
sebaran bin per jumlah orang.

Kalau muncul peringatan **">20% tidak berlabel"**, artinya pencatat label tidak
menutupi seluruh durasi kolektor — biasanya karena dijalankan terlambat atau
dihentikan duluan. Data tetap terpakai, tapi sebagian terbuang.

---

## Kenapa `--bin-ms 100`

Sudah diuji di proyek ini: 100 ms memberi coverage 97.4% dengan 4 board. Bin lebih
kecil memecah paket ke bin berbeda; bin lebih besar mengaburkan perpindahan orang
antar zona. Jangan diubah tanpa alasan.

---

## Kesalahan yang paling sering, dan akibatnya

| Kesalahan | Akibat | Terlihat dari |
|---|---|---|
| Dua sesi menumpuk di satu folder | Coverage salah tapi tampak wajar | `csi_merge --stats-only` kacau |
| Pencatat label dijalankan telat | Bin awal terbuang | Peringatan ">20% tidak berlabel" |
| Board dinyalakan bergantian | Coverage jatuh | Node < 4 di kolektor |
| Lupa tekan saat orang pindah zona | Label salah, senyap | **Tidak terlihat sama sekali** |
| Router bergeser | Sesi tidak sebanding | Tidak terlihat sama sekali |

Dua baris terakhir tidak punya alarm otomatis. Itulah kenapa batas zona harus
dilakban dan router tidak boleh disentuh.

---

## Yang perlu dilaporkan / disimpan

1. Output `csi_merge.py --stats-only` tiap sesi
2. Sebaran kelas dari `label_occupancy.py`
3. Catatan kondisi: jumlah orang, siapa saja, jam berapa, pintu terbuka/tutup

Data `.bin` + `occupancy.csv` di tiap folder `capture\count_*` sudah cukup untuk
mengulang analisis kapan saja — **jangan hapus** meskipun CSV-nya sudah jadi.

---

## Sesi yang PALING BERHARGA berikutnya (prioritas 1, per 2026-09-19)

> Ini bukan saran umum. Setelah analisis `data-14-9` **dan** `data-15-9`, ini
> satu-satunya pengambilan data yang membuka pertanyaan riset yang masih tertutup.
> Lihat `KNOWLEDGE.md` §13.7 untuk alasan lengkapnya.

### Masalahnya

Kedua dataset punya cacat struktural yang **sama**: satu sesi = satu tingkat
okupansi yang nyaris konstan. Akibatnya "kosong vs terisi" selalu jadi
perbandingan **antar-sesi**, tak terpisahkan dari jam perekaman dan drift kanal.

Di `data-15-9`: **316 dari 336** jendela kosong berasal dari satu sesi
(`count_2_9`) saja. Sesi lain menyumbang 1–11 jendela di detik-detik awalnya.
Tidak ada model yang bisa menambal ini.

### Yang harus dilakukan

**Satu perekaman KONTINU melintasi bubarnya kelas. Jangan hentikan kolektor.**

```
  kelas penuh  →  mahasiswa keluar bertahap  →  ruangan kosong
  └──────────────── SATU file .bin per board ─────────────────┘
```

1. Mulai kolektor **10 menit sebelum** kelas berakhir, saat ruangan masih penuh.
2. **Jangan hentikan** saat kelas bubar. Biarkan terus merekam.
3. Terus merekam **10 menit setelah** orang terakhir keluar.
4. Catat label live seperti biasa (`mark_occupancy.py`), tekan saat orang keluar.
5. Total ~25–30 menit, satu folder, satu sesi.

### Kenapa ini mengubah segalanya

- Memberi **kosong DAN terisi di DALAM satu sesi** → deteksi berubah dari klaim
  antar-sesi yang confounded menjadi klaim dalam-sesi. Jam perekaman, drift
  kanal, dan identitas sesi jadi konstan, bukan variabel pengganggu.
- Memberi ramp **N→0 yang nyata** dengan timestamp yang bisa dipercaya → satu-satunya
  jalan yang tersedia untuk counting.
- Biayanya **satu perekaman**. Kalau baru disadari setelah pengumpulan selesai,
  yang hangus satu hari penuh.

### Yang tidak boleh dilakukan

- **Jangan** hentikan lalu mulai ulang perekaman saat kelas bubar. Dua file =
  dua sesi = cacat yang sama terulang.
- **Jangan** mengandalkan satu sesi kosong terpisah lagi. Itu yang sudah ada dua
  kali, dan itu yang membuat hasilnya confounded.
- **Jangan** mengatur mahasiswa. Bubarnya kelas sudah memberi transisi alami.

### Prioritas berikutnya setelah itu

2. **Beberapa sesi kosong di jam dan hari berbeda** (sebelum kelas, jam istirahat,
   hari tanpa jadwal). Supaya "kosong" bukan satu titik waktu. Masing-masing 5
   menit, tidak butuh kerja sama siapa pun.
3. **Kelas dengan ukuran berbeda** — variasi jumlah orang antar sesi tanpa
   mengatur siapa pun.
4. **Untuk klaim zona:** catat di mana mahasiswa duduk tiap sesi. Saat ini semua
   zona naik bersamaan (`corr(C, total)` = +0.85), jadi efek zona tidak
   terpisahkan dari jumlah total. Kalau pola duduk berbeda antar kelas, data zona
   terkumpul sendiri.
