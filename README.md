# AkriBox

> Dari gambar 2D ke potongan laser yang pas.

Merakit gambar 2D panel akrilik (file AI / PDF) menjadi rakitan 3D virtual, lalu memeriksa
apakah semuanya pas di ukuran nyata **sebelum** dipotong: tab masuk slot atau tidak, panel
bertabrakan atau tidak, dan berapa ukuran jadi box-nya. Hasil akhirnya DXF/SVG siap potong.

## Pasang dan jalankan

Butuh Python 3.12 (Windows; Linux/macOS seharusnya jalan, belum diuji).

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
box.bat new kotak.box.json --inner 120,90,60 --tebal 5
box.bat gui kotak.box.json
```

Contoh proyek siap pakai ada di `examples/kotak-contoh.box.json`. Untuk pengujian GUI otomatis
pasang juga `requirements-dev.txt` (Playwright, memakai Chrome sistem).
Pada contoh di bawah, `box` berarti `box.bat` (Windows) atau `python -m boxapp`.

Lisensi: [MIT](LICENSE). Komponen (USB, OLED, ESP32, dll.) memakai ukuran umum/perkiraan:
cocokkan dengan komponen asli sebelum memotong akrilik.

Satu engine, dua pintu masuk: **GUI** di browser dan **CLI** (untuk dipakai LLM). Keduanya
membaca file proyek yang sama, `*.box.json`.

## Desain dari nol (generator box)

```
box new kotak.box.json --inner 120,90,60 --tebal 5     proyek baru tanpa gambar, ukuran DALAM (mm)
box check kotak.box.json                               rakitan lolos dari rumusnya
box gui kotak.box.json                                 edit di GUI (tombol Generator box... mengubah ukuran)
box generator kotak.box.json --inner 150,100,70 --tab 25 --no-top --count-span 4
```

Enam panel (G1 alas, G2 atas, G3 depan, G4 belakang, G5 kiri, G6 kanan) dibuat dengan tab dan
slot yang pasti berpasangan, sudah terpasang di rakitan, dan ukuran luarnya = ukuran dalam + 2 x tebal.
Tiga jenis sambungan (tegak, samping, lebar) diatur lewat jumlah tab; mengubah satu jenis otomatis
mengubah kedua panel yang bersambung, jadi tab dan slot tidak pernah berselisih. Lubang, kotak,
larik, dan gambar-ke-bentuk tetap bisa ditambahkan ke panel hasil generator. Generator bisa juga
ditambahkan ke proyek yang sudah punya gambar sumber.

Hapus panel (juga panel dari gambar AI): tombol Hapus panel di tab 2D, atau
`box remove-panel PROYEK G2` (`--restore` untuk memulihkan). Panel yang dihapus tidak ikut
rakitan maupun ekspor, dan muncul di daftar "Dihapus" untuk dipulihkan.

## Pustaka komponen

Tombol **Komponen…** di tab Panel 2D (atau `box components` / `box component`) menaruh potongan
standar sebagai satu grup yang bergerak dan terhapus bersama: lubang baut M2–M6, 4 lubang baut PCB,
kipas PC 40–120 mm (bukaan + 4 baut), tombol bulat Ø12–30, LCD 16×2, jendela layar + 4 baut,
soket kotak + 2 baut, port USB betina (A/B/Micro/C, cangkang + bukaan), OLED 0,96 inci SPI, soket AC IEC C14, dan ventilasi heksagonal. Pratinjau dan ukuran dihitung backend.

```
box components                                          daftar dan parameternya
box component kotak.box.json G3 kipas --param size=80 --at 80,45
box component kotak.box.json G4 ventilasi --param w=100 --param h=50 --param d=6 --param pitch=10
```

Ukuran adalah nilai umum (lubang baut menurut ISO 273, pola baut kipas PC, lubang tombol standar).
Komponen yang ukurannya beda antar pabrik (soket, layar, jack) bersifat kustom; isi dari datasheet
komponen Anda. Cocokkan dengan komponen asli sebelum memotong akrilik.

## Bentuk tidak kotak (trapesium, geser titik)

Di tab Panel 2D (alat Pilih), tiap panel punya **titik sudut** (lingkaran) dan **pegangan sisi** (belah ketupat di tengah sisi):

- seret titik = geser sudut; seret pegangan sisi = geser seluruh sisi (kedua ujungnya);
- klik dua kali pegangan sisi = sisipkan titik baru; pilih titik lalu **Delete** = hapus titik;
- titik terpilih bisa diketik x, y-nya; semua posisi dibulatkan backend sesuai Langkah (bawaan 1 mm), jadi hanya sisi miring yang berkoma;
- **Trapesium**: pilih sisi, isi berapa mm ujung 1 dan ujung 2 dipendekkan (mis. atas 12 dan 12), Terapkan;
- **Reset bentuk** mengembalikan outline bawaan.

CLI: `box outline PROYEK PANEL` (daftar titik), `--trapezoid top 12 12`, `--vertex 3 85 52`, `--insert 2`, `--remove 3`, `--reset`.

Catatan: tab di sisi yang bergeser ikut bergeser dan ikut berputar mengikuti sisinya, tetapi panel pasangannya TIDAK otomatis menyesuaikan. Generator box tetap menghasilkan box persegi panjang; setelah outline diubah, jalankan `check`, dan perhatikan peringatan sambungan. Titik outline disimpan mutlak, jadi bila ukuran generator diubah sesudahnya, ulangi atau reset bentuknya.

## Tengahkan, skala, dan bagi sisi (tab otomatis)

| Fitur | GUI (tab Panel 2D) | CLI |
|---|---|---|
| Tengahkan bentuk di panel | pilih bentuk, lalu ⌖ (tengah), ↔ (kiri-kanan), ↕ (atas-bawah) | `box align P PANEL F1,F2 --mode center` (juga left, right, top, bottom) |
| Perbesar / perkecil bentuk | kolom Skala % lalu Terapkan, atau tombol − / + (10%) | `box scale P PANEL F1 --percent 150 [--about selection]` |
| Bagi sisi jadi N bagian | tombol **Bagi sisi...** | `box divide P PANEL --edge bottom --parts 3 [--mate-panel G5 ...]` |
| Zoom tampilan | tombol − / + di bilah, tombol keyboard - dan +, roda mouse | (hanya GUI) |

**Bagi sisi**: sisi panel dibagi menjadi N bagian sama panjang, dan tab mengisi bagian selang-seling
(mis. 120 mm / 3 = tab 0-40, jarak 40-80, tab 80-120). Panjang tab dan jaraknya dihitung backend dan
ditampilkan; bila tidak habis dibagi, batas dibulatkan ke bilangan bulat dan ada catatannya. Pilihan:
pola selang-seling (mulai dari tab atau jarak) atau tab di tengah tiap bagian, jarak dari ujung, tab
keluar atau slot masuk, kedalaman, dan mengganti tab lama di sisi itu. Bila "buat pasangannya" dipilih,
panel lain mendapat slot (atau tab) dengan pembagian yang sama persis; "balik urutan" untuk panel yang
berhadapan, "awal sisi sepanjang pasangan" untuk menggeser posisi awalnya.

Skala membulatkan ukuran ke kisi Langkah, kecuali bentuk miring. Tab tidak bisa diskala; geser atau
hapus tab lewat pilih lalu Delete, atau buat ulang dengan Bagi sisi.

## Menghapus

| Yang dihapus | Cara |
|---|---|
| Bentuk, tab, atau seluruh komponen | tab Panel 2D: pilih, lalu Delete atau tombol Hapus |
| Panel | tombol ✕ di daftar panel, tombol Hapus panel (bar 3D, bagian Posisi di rakitan, atau baris bawah tab 2D), atau Delete di tampilan 3D |
| Memulihkan | Ctrl+Z, atau daftar "Dihapus" di bawah daftar panel (`box remove-panel ... --restore`) |

## Pasang

Butuh Python 3.11+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Pakai

```
box init gambar.ai -o casing.box.json --tebal 5    buat file proyek
box info casing.box.json                           daftar panel, tab, slot (koordinat mm)
box mates casing.box.json                          saran pasangan tab -> slot
box check casing.box.json                          rakit 3D + periksa (exit 0 = lolos)
box check casing.box.json --kerf 0.2 --detail      coba kerf lain, rinci per tab
box check casing.box.json --json                   laporan lengkap untuk program / LLM
box render casing.box.json -o rakitan.png          gambar 3D (--view, --explode 0.8)
box export casing.box.json -o hasil                DXF + SVG siap potong
box gui casing.box.json                            buka GUI
```

Menyunting bentuk (semua tersimpan di file proyek; gambar sumber tidak disentuh):

```
box add-circle casing.box.json P7 --at 65,20 --d 10            lubang bulat (koordinat panel, mm)
box add-rect   casing.box.json P7 --at 65,40 --size 30,12      potongan kotak (--angle untuk memutar)
box add-poly   casing.box.json P7 --points "0,0 10,0 10,8"     potongan poligon
box array      casing.box.json P5 --circle 6 --from 20,20 --count 6,4 --pitch 12,10.4 --stagger
box move       casing.box.json P4 F12,T3 --by 3,0              geser fitur / tab
box delete     casing.box.json P4 F5 T2                        buang fitur / tab (restore = kembalikan)
box new-panel  casing.box.json --size 100,60 --name plat       panel kotak baru
box trace      casing.box.json foto.png --lebar 160 --new-panel   gambar -> bentuk nyata
box edit       casing.box.json '[{"op":"add","panel":"P7","shape":{"kind":"circle","center":[65,20],"d":10}}]'
```

Ukuran dan batas panel:

```
box measure casing.box.json P2                  laporan ukuran: batas, sisi (termasuk miring), yang berkoma
box edge    casing.box.json P2 --right 155 --top 180   atur batas ke posisi mutlak (mm, dibulatkan)
box edge    casing.box.json P2 --round          bulatkan semua batas yang berkoma
```

Aturan angka: ukuran dan posisi berupa bilangan bulat (mm), kecuali sisi dan bentuk miring.
Semua pengukuran, pembulatan, dan snap dihitung di backend (`boxapp/measure.py`); GUI hanya
mengirim koordinat mentah ke `/api/measure` dan `/api/edit` lalu menampilkan jawabannya, jadi GUI,
CLI, dan LLM selalu mendapat angka yang sama. Memindahkan batas menggeser titik outline yang ada
di batas itu dan tab yang menempel; lubang dan slot tidak ikut bergeser.

`box info` menampilkan id fitur (F..), tab (T..), dan bentuk tambahan (A..) untuk dipakai di
`move` / `delete`.

## Melihat dan mengendalikan GUI dari baris perintah (untuk LLM)

Butuh `pip install -r requirements-dev.txt` (Playwright) dan Chrome atau Edge yang sudah
terpasang. Aplikasi dijalankan di browser tanpa kepala, jadi tidak perlu membuka apa pun.

```
box shot  casing.box.json -o layar.png --tab 2d --panel P7
box drive casing.box.json skrip.json --outdir hasil [--apply]
```

`drive` menjalankan langkah JSON (klik, seret dalam mm panel, ketik, unggah gambar, tangkapan
layar, ringkasan `state`); daftar langkah ada di `boxapp/drive.py`. Bawaannya hanya mengubah
salinan sementara; `--apply` menyimpan ke proyek asli. Saat satu langkah gagal, layar pada saat
itu disimpan sebagai `gagal.png`.

Ini browser terpisah, bukan Chrome Anda yang sedang terbuka.

## Menyunting di GUI

Buka tab **Panel 2D**, pilih panel, lalu:

| Aksi | Cara |
|---|---|
| Pilih / geser bentuk | alat Pilih (V): klik, seret; Shift = banyak |
| Gambar lingkaran | alat Lingkaran (C): seret dari pusat ke tepi; klik saja = Ø 8 mm |
| Gambar kotak | alat Kotak (B): seret dari sudut ke sudut; klik saja = 20 × 6 mm |
| Ubah ukuran tepat | pilih bentuk, ubah angka di baris bawah (x, y, Ø, lebar, tinggi, sudut) |
| Ubah luas panel | seret tepi panel (kiri / kanan / atas / bawah) atau ketik di baris bawah; angka batas selalu bulat; Bulatkan = rapikan yang berkoma, Reset batas = kembali ke gambar sumber |
| Hapus | Delete atau tombol Hapus (bentuk bawaan gambar pun bisa, lalu diurungkan) |
| Larik lubang | tombol Larik...: grid atau selang-seling, menghindari tepi dan potongan lain |
| Zoom / geser tampilan | roda mouse / spasi atau klik kanan + seret |
| Urungkan / ulangi | Ctrl+Z / Ctrl+Shift+Z (berlaku juga untuk gizmo 3D) |

"Langkah" mengatur kelipatan penempatan (mm); 0 = bebas. Setelah tiap perubahan, rakitan 3D dan
laporan dihitung ulang otomatis.

### Gambar → bentuk

Tombol **Gambar → bentuk...** mengubah PNG/JPG menjadi bentuk vektor berukuran nyata, dengan
pratinjau langsung. Isi satu ukuran yang diketahui (lebar atau tinggi seluruh bentuk, mm) agar
skalanya benar; ketelitian sekitar 1 piksel gambar.

| Kondisi gambar | Pengaturan |
|---|---|
| Objek jelas di latar polos (siluet, pelat) | mode **Ambang** (otomatis) |
| Foto dengan cahaya tidak rata (kertas, bayangan) | mode **Adaptif** |
| Objek tanpa isi seragam, hanya terlihat tepinya | mode **Tepi** |
| Garis outline saja | centang "abaikan lubang" agar bagian dalam garis terisi |
| Kontras rendah / berbintik | naikkan Kontras, centang CLAHE, Blur 3-5 |
| Bingkai foto ikut terbaca | centang "buang yang menyentuh tepi gambar" |

Hasilnya bisa dipakai sebagai potongan di panel terpilih atau sebagai **panel baru** (bentuk
terbesar jadi outline, lubangnya jadi potongan). Lubang bulat hasil gambar berupa poligon halus
(toleransi 0,2 mm), bukan lingkaran sejati.

Gambar sumber harus vektor skala 1:1. File `.ai` harus disimpan dengan opsi
"Create PDF Compatible File" (bawaan Illustrator). Dari CorelDRAW: ekspor ke PDF.

## Mengedit di GUI (gizmo)

Pilih panel, lalu seret panah (geser) atau cincin (putar) di tampilan 3D. Saat dilepas,
posisi baru tersimpan ke file proyek dan rakitan diperiksa ulang.

| Tombol | Fungsi |
|---|---|
| G / R | mode geser / putar |
| X, Y, Z | kunci ke satu sumbu (tekan lagi untuk lepas) |
| Ctrl+Z | urungkan |
| Esc | batal pilih |

"Langkah" mengatur kelipatan geser (mm) dan putar (derajat); 0 = bebas. Gizmo hanya aktif
saat slider Urai di nol.

## File proyek

Geometri tidak disimpan di file proyek; selalu dibaca ulang dari gambar sumber. Yang
disimpan hanya tebal, kerf, nama panel, dan posisi rakitannya:

```json
{
  "source": "gambar.ai",
  "thickness": 5.0,
  "kerf": 0.0,
  "panels": {
    "P4": {
      "name": "samping_kanan",
      "placement": {"origin": [0, 0, 0], "u": "+X", "v": "+Z"},
      "roles": {"F12": "guide"}
    }
  }
}
```

- `placement`: titik (x, y) lokal panel dipetakan ke `origin + x*u + y*v`. Koordinat lokal:
  (0, 0) = pojok kiri-bawah outline panel, y ke atas. Tebal panel memanjang dari bidang itu
  ke arah `u x v`. `u` / `v` boleh `"+X"`, `"-Y"`, ... atau vektor `[x, y, z]`.
- Panel tanpa `placement` tidak ikut dirakit.
- `edits`: perubahan bentuk per panel: `add` (bentuk tambahan `A1`...), `move` dan `delete`
  (untuk fitur `F..` dan tab `T..` bawaan gambar). Panel baru ditulis sebagai
  `"N1": {"new": {"size": [100, 60]}}`. Koordinat panel: (0,0) = pojok kiri-bawah outline.
- `roles`: timpa peran fitur di dalam panel: `cut` (dipotong), `guide` (garis bantu), `ignore`.
  Bawaan: bentuk dalam yang menutupi >= 70% panel dianggap garis bantu, sisanya dipotong.

## Alur kerja dengan LLM

1. `box init`, lalu `box info` dan `box mates` untuk membaca panel dan pasangan tab-slot.
2. LLM mengisi `placement` tiap panel di file proyek.
3. `box check` (dan `box render` untuk melihat hasilnya); perbaiki sampai sesuai.
4. GUI yang sedang terbuka memuat ulang sendiri setiap file proyek berubah.

## Arti laporan

| Level | Arti |
|---|---|
| gagal | tab tidak muat (kurang > 0,5 mm), tab menabrak bagian pejal, atau badan panel saling menembus |
| sesak | kurang <= 0,5 mm; biasanya ketidaktelitian gambar, bisa tertutup kerf |
| awas | tab menggantung, slot kosong, tab digambar terlepas dari tepi |

Kerf: slot melebar setengah kerf per sisi, panjang tab menyusut setengah kerf per sisi.
Rakitan 3D sendiri memakai ukuran nominal gambar.

## Batasan

- Hanya halaman pertama file yang dibaca.
- Ukuran outline panel bawaan gambar belum bisa diubah (hanya panel baru berbentuk kotak, lewat
  `resize_panel`); sambungan tab-slot tidak diselaraskan otomatis, geser manual lewat `move`.
- Posisi rakitan tidak ditebak otomatis; diisi lewat file proyek atau GUI.
- Tab dikenali sebagai bentuk kecil di luar panel yang menempel (<= 1 mm) ke tepinya.

> Bagi sisi mode slot: bila sudut sudah berisi slot milik sisi tegak lurus (mis. atas/bawah sudah dibagi), panjang di ujung sisi ini otomatis dikurangi sebesar slot itu supaya tidak saling menimpa. Bisa dimatikan di dialog (opsi `corner`).

## Magnet dan garis panduan

Centang **Magnet** di bilah Panel 2D (bawaan aktif). Saat menyeret bentuk, menggambar lingkaran/kotak, atau menyeret titik outline, tepi dan tengahnya menempel ke tepi/tengah bentuk lain dan panel, dengan garis magenta sebagai panduan. Tahan **Alt** untuk mematikan sementara. Jarak tempel 7 piksel layar; semua hitungan di backend (`/api/measure`), hasil akhir sama dengan pratinjau. Posisi hasil magnet boleh berkoma (mis. tengah panel ganjil); tanpa magnet posisi mengikuti Langkah.

## Salin, tempel, gandakan

Pilih bentuk atau grup di Panel 2D, lalu **Ctrl+C** (Salin), **Ctrl+V** (Tempel), atau **Ctrl+D** (Gandakan di tempat). Tempel di panel yang sama bergeser 10 mm (berjenjang bila diulang); tempel di panel lain mengambil posisi yang sama. Grup dan komponen disalin sebagai grup baru. Tab tidak ikut disalin. CLI: `box duplicate PROYEK PANEL A1,A2 [--to PANEL] [--dx 5 --dy -5]`.

## Slot otomatis dari tab

Tombol **Slot otomatis…** (atau `box auto-slots PROYEK [--dari PANEL] [--clearance 0.1]`) membuat slot di panel lawan untuk setiap tab yang menabrak bagian pejal (laporan Periksa: tidak ada slot di posisi ini). Ukuran dan posisi slot diambil dari penampang tab pada bidang panel lawan di rakitan 3D, ditambah celah opsional. Panel harus sudah ditempatkan. Tab yang tidak menyentuh panel mana pun tidak diproses.

## Sambungan otomatis (tab + slot dari 3D)

Tombol **Sambungan otomatis…** (CLI: `box auto-joint PROYEK DARI KE --parts 5`): backend mencari sisi panel DARI yang menempel ke permukaan panel KE di rakitan 3D, membuat tab selang-seling di sisi itu, membuang slot lama yang dipakai tab yang diganti, lalu memotong slot baru di KE tepat di penampang tab. Syarat: kedua panel sudah ditempatkan dan sisinya menempel (jarak maks 1,5 mm; selebihnya ditolak dengan pesan jaraknya). `box auto-slots` hanya membuat slot untuk tab yang sudah ada.

## Magnet di rakitan 3D

Saat gizmo geser dilepas, backend membulatkan geseran ke Langkah lalu menempelkan permukaan panel ke permukaan panel lain yang berdekatan (maks 8 mm, kotak **Magnet** di kontrol 3D). Koreksi terkecil dipakai dulu, lalu dihitung ulang (maks 3 sumbu). Tombol **Tempelkan** di panel Posisi (CLI: `box snap PROYEK PANEL [--ke PANEL] [--tol 30]`) menempelkan panel terpilih sampai jarak 30 mm, bisa ke panel tertentu bila ada dua dinding berhadapan. Hanya menempel bila kedua panel berhadapan (beririsan di bidang).

## Warna panel dan latar 3D

Di tab 3D: pilih panel, lalu ubah **Warna** di panel Posisi (disimpan di proyek; **Bawaan** mengembalikan warna otomatis). Menu **Latar** mengganti warna latar tampilan 3D (gelap/terang/putih/abu/warna lain), tersimpan di browser. Hanya tampilan; tidak memengaruhi DXF/SVG, dan gambar `box render` masih memakai warna bawaan.
