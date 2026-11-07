# RUNBOOK — Capture CSI multi-STA (dipakai saat OFFLINE)

Dokumen ini untuk dipakai **tanpa internet**, saat laptop sudah pindah ke router
`<SSID>`. Semua perintah bisa disalin apa adanya.

> Firmware sudah di-build dan `COLLECTOR_IP` sudah diset ke **<IP_LAPTOP>**.
> Tidak perlu build ulang kecuali ada yang diubah.
>
> **VERSI v2 (2026-09-09 sore).** Perubahan dari v1: batching TCP dimatikan,
> filter `sig_len=114`, `seq` baru dihitung setelah link kolektor siap, dan
> buffer basi dibuang saat reconnect. Format frame berubah (42 B -> 50 B), jadi
> firmware v2 HARUS dipakai dengan tools v2. Backup v1 lengkap ada di
> `backup/v1_tcp_batched_20260909/`.

## URUTAN YANG BENAR — kolektor DULU, board KEMUDIAN

Di v1 board dinyalakan lebih dulu, dan hasilnya jam board merentang 141 detik
sementara host hanya 59 detik — ada lubang 69 detik saat board menunggu kolektor.
v2 sudah membuang paket sebelum link siap, tapi urutan yang benar tetap:

1. Jalankan `csi_collector.py` **sampai muncul "Kolektor siap"**
2. Baru nyalakan / reset board — **semua board sekaligus**

> **SATU SESI = SATU FOLDER.** Selalu pakai `--outdir` baru tiap capture
> (`sesi1`, `sesi2`, ...). Kolektor tidak menghapus isi folder lama, dan
> `csi_merge.py` akan membaca SEMUA `.bin` di situ sebagai satu capture --
> hasilnya angka coverage yang salah tapi kelihatan masuk akal.
>
> **Keempat board harus hidup BERSAMAAN.** Kalau dinyalakan bergantian, jendela
> waktunya tidak beririsan dan coverage jadi 0% -- itu benar, bukan bug.


---

## Ringkasan alur

```
1. Pindah ke <SSID> (2.4 GHz)   -> cek IP harus <IP_LAPTOP>
2. Jalankan kolektor                 -> terminal #1, biarkan terbuka
3. Flash board #1                    -> terminal #2
4. Verifikasi max_len=512 & link=up
5. Flash board #2 (binary yang SAMA) -> port berbeda
6. Capture, lalu Ctrl-C kolektor
7. Cek hasil dengan csi_merge.py
```

**Satu binary untuk semua board.** `node_id` diturunkan dari MAC saat runtime, jadi
tidak ada build khusus per board dan tidak mungkin salah label.

---

## Langkah 1 — Pindah jaringan & cek IP

Sambungkan laptop ke **`<SSID>` (2.4 GHz, bukan 5 GHz)**.

Supaya Windows tidak diam-diam balik ke kampus di tengah capture:

```powershell
netsh wlan set profileparameter name="<JARINGAN_LAIN>" connectionmode=manual
```

Lalu cek:

```powershell
ipconfig | findstr /i "IPv4 Gateway"
```

**Harus muncul:**

```
IPv4 Address. . . . . . . . . . . : <IP_LAPTOP>
Default Gateway . . . . . . . . . : 192.168.50.1
```

> **Kalau alamatnya BUKAN <IP_LAPTOP> — berhenti di sini.** Firmware menembak ke <IP_LAPTOP>, jadi
> board tidak akan pernah nyambung. Catat alamat yang benar-benar didapat, lalu
> `COLLECTOR_IP` di `main/app_main.c` harus diubah dan firmware di-build ulang
> (butuh internet untuk sesi berikutnya, atau build offline kalau toolchain sudah
> lengkap: `idf.py build`).

---

## Langkah 2 — Jalankan kolektor (terminal #1)

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2
python tools\csi_collector.py --outdir capture\sesi1 -v
```

Tanda sehat:

```
Kolektor siap di 0.0.0.0:5566 -> capture\sesi1
Menunggu koneksi ESP... (Ctrl-C untuk berhenti)
```

**Biarkan terminal ini terbuka selama capture.** Kalau Windows Firewall bertanya,
izinkan akses di jaringan Private.

---

## Langkah 3 — Flash board #1 (terminal #2)

```powershell
cd D:\SKRIPSI\code\CSI-PeopleCounting\esp\RISET_CSI_2
$env:PATH = "$env:USERPROFILE\.espressif\tools\idf-python\3.11.2;" + $env:PATH
. C:\esp\v5.5.2\esp-idf\export.ps1
idf.py -p COM15 flash monitor
```

> Baris `$env:PATH` itu **wajib**. Tanpa itu `export.ps1` mencari virtualenv py3.12
> yang tidak ada dan gagal. Lihat KNOWLEDGE.md.

Keluar dari monitor: `Ctrl-]`

---

## Langkah 4 — Verifikasi board #1

Di **monitor**, yang harus terlihat berurutan:

```
Node MAC 60:cf:84:xx:xx:xx -> node_id 0xNN
STA connected, BSSID <MAC>, channel 11
Got IP 192.168.50.xxx, gateway 192.168.50.1
Tersambung ke kolektor <IP_LAPTOP>:5566
node=NN rx=52 sent=52 drop=0 max_len=512 oversize=0 link=up
```

Di **kolektor**:

```
Koneksi masuk dari 192.168.50.xxx
[192.168.50.xxx] node_id=0xNN mac=... -> capture\sesi1\nodeNN_..._....bin
```

**Dua angka yang menentukan:**

| Cek | Harus | Artinya kalau salah |
|---|---|---|
| `max_len` | **512** | Bandwidth/protokol tidak sesuai (bukan HE20) |
| `filt` | naik pelan | Normal: itu frame `sig_len!=114` yang sengaja dibuang (v2) |
| `link` | **up** | Kalau `down`, board tidak bisa menjangkau laptop |
| `drop` | kecil / 0 | Kalau naik terus, kolektor tidak menyusul |

Kalau keempatnya sehat, lanjut. Kalau tidak, lihat tabel masalah di bawah.

---

## Langkah 5 — Flash board #2

**Binary yang sama persis.** Colok board #2, cari portnya:

```powershell
python -c "import serial.tools.list_ports as p; [print(x.device, x.description) for x in p.comports()]"
```

Lalu flash (ganti `COMxx` sesuai hasil di atas):

```powershell
idf.py -p COMxx flash monitor
```

Kolektor sekarang harus menampilkan **dua** koneksi dengan MAC berbeda dan menulis
**dua** file `.bin` terpisah.

> Setelah di-flash, board tidak perlu USB ke laptop — cukup sumber daya USB apa saja
> (powerbank, charger). Itulah gunanya jalur TCP: board bisa ditaruh di mana saja.

---

## Langkah 6 — Capture

Biarkan berjalan selama durasi yang diinginkan, lalu **Ctrl-C** di terminal kolektor.

Ringkasan akan tercetak otomatis:

```
Total NNN paket dari 2 node aktif.
  nodeNN_...: NNN paket, gap=N -> capture\sesi1\...bin
```

Untuk capture berdurasi tetap (mis. 5 menit), pakai:

```powershell
python tools\csi_collector.py --outdir capture\sesi1 --duration 300 -v
```

---

## Langkah 7 — Cek hasil

```powershell
python tools\csi_merge.py capture\sesi1 --stats-only --bin-ms 150
```

v2 memakai jam board + offset untuk merekonstruksi waktu capture, jadi keluaran
juga menampilkan jitter jaringan yang berhasil dibuang. Untuk membandingkan
dengan cara lama: tambahkan `--use-host-time`.

Contoh keluaran sehat:

```
Node          : 2
  node 60:cf:84:...: 600 paket, 10.0 pkt/s, hilang=2, rssi -45..-38
  node 60:cf:84:...: 598 paket, 10.0 pkt/s, hilang=3, rssi -52..-44
Bin 150 ms   : ... berisi semua 2 node (9x%)
```

Yang dilihat: **~10 pkt/s per node**, `hilang` kecil, dan persentase bin berisi semua
node tinggi (>90%).

Untuk menulis CSV:

```powershell
python tools\csi_merge.py capture\sesi1 -o sesi1.csv --bin-ms 150
```

---

## Kalau ada masalah

| Gejala | Kemungkinan penyebab | Tindakan |
|---|---|---|
| `connect() ... gagal` berulang | Laptop bukan di <IP_LAPTOP>, atau kolektor belum jalan | Cek `ipconfig`; pastikan terminal #1 hidup |
| `link=down` tapi `rx` naik | CSI masuk, TCP tidak nyambung | Cek firewall Windows, cek IP laptop |
| `rx=0` terus | Tidak ada CSI sama sekali | Router harus di **channel 11** dan **802.11ax (AX/HE) aktif**. Kalau router jatuh ke mode legacy/HT, callback memang sunyi. |
| `max_len` bukan 512 | Bandwidth bukan HE20 | Catat nilainya, laporkan |
| `oversize` naik | Paket melebihi buffer | Catat `max_len`, laporkan |
| Board tidak connect WiFi | SSID/password salah, atau router 5 GHz | SSID harus `<SSID>` 2.4 GHz |
| Kolektor tidak lihat koneksi | Firewall memblok port 5566 | Izinkan Python di jaringan Private |
| `gap` besar sekali | Paket hilang banyak | Catat angkanya, laporkan |

**Firewall** adalah penyebab paling sering kalau board bilang gagal connect padahal
jaringan benar. Kalau ragu, jalankan sekali sebagai Administrator:

```powershell
New-NetFirewallRule -DisplayName "CSI Collector 5566" -Direction Inbound -LocalPort 5566 -Protocol TCP -Action Allow
```

---

## Yang perlu dilaporkan setelah kembali online

1. Output `csi_merge.py --stats-only`
2. Satu baris statistik dari monitor (`node=.. rx=.. sent=.. drop=.. max_len=..`)
3. Kalau gagal: pesan error dari monitor **dan** dari kolektor

Data `.bin` tetap tersimpan di `capture\sesi1\` — aman untuk dianalisis nanti.
