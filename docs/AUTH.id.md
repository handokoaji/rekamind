🌐 [English](AUTH.md) · **Bahasa Indonesia**

# Login dan hak akses Rekamind

Rekamind open source (AGPL-3.0-or-later). Siapa pun boleh memasangnya di servernya sendiri. Karena itu **tidak ada
kredensial Google bawaan**: setiap pemasang membuat OAuth client Google sendiri dan memasukkannya lewat
variabel lingkungan. Rahasia tidak pernah ada di repo, di browser, atau di aplikasi desktop.

## Aturan akses

| Peran | Boleh |
|---|---|
| **User** | Hanya melihat dan mengubah rapat, task, dan peserta **miliknya sendiri**. Data orang lain dijawab `404` (bukan `403`, supaya keberadaannya tidak bocor). |
| **Super admin** | Semua: melihat semua rapat (tombol "Semua pengguna"), mengundang/menonaktifkan pengguna, menaikkan/menurunkan peran. Daftar super admin awal datang dari `REKAMIND_SUPERADMINS`. Super admin aktif terakhir tidak bisa diturunkan atau dinonaktifkan. |

Siapa yang boleh membuat akun:
- `REKAMIND_SIGNUP=allowlist` (bawaan): hanya email di `REKAMIND_ALLOWED_EMAILS`, domain di `REKAMIND_ALLOWED_DOMAINS`, super admin, atau yang diundang super admin.
- `REKAMIND_SIGNUP=open`: setiap akun Google dengan email terverifikasi. Hanya pakai ini bila Anda memang ingin server terbuka.

## 1. Membuat OAuth client Google (sekali, oleh pemasang)

> Langkah di Google Cloud Console berubah dari waktu ke waktu dan **tidak bisa saya verifikasi dari
> lingkungan pengembangan ini** (host Google diblokir). Perlakukan nama menu di bawah sebagai petunjuk, dan
> cocokkan dengan dokumentasi Google terbaru.

1. Buka Google Cloud Console, buat project, lalu atur layar persetujuan OAuth (OAuth consent screen).
   Untuk pemakaian internal organisasi Google Workspace pilih tipe *Internal*; selain itu *External*.
   Status "Testing" membatasi ke daftar test user dan bisa membuat refresh token kedaluwarsa. Itu tidak
   masalah di sini karena Rekamind hanya meminta scope `openid email profile` dan membuat sesinya sendiri.
2. Buat kredensial: *OAuth client ID*, tipe *Web application*.
3. **Authorized redirect URI** diisi persis: `{REKAMIND_PUBLIC_URL}/auth/callback`
   (contoh `https://rekamind.kantor.id/auth/callback`).
4. Salin Client ID dan Client secret ke env server.

## 2. Konfigurasi server

```env
REKAMIND_AUTH=google
REKAMIND_PUBLIC_URL=https://rekamind.kantor.id   # harus https (kecuali localhost)
REKAMIND_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
REKAMIND_GOOGLE_CLIENT_SECRET=xxxx
REKAMIND_SUPERADMINS=anda@kantor.id              # pisahkan koma
REKAMIND_SIGNUP=allowlist
REKAMIND_ALLOWED_DOMAINS=kantor.id
# opsional: REKAMIND_ALLOWED_EMAILS, REKAMIND_SESSION_DAYS (14), REKAMIND_DESKTOP_SESSION_DAYS (30)
```

Server **menolak start** bila konfigurasinya tidak aman: Google tanpa client id/secret/public URL, public URL
bukan https, `signup` tidak dikenal, atau `REKAMIND_AUTH=none` di alamat selain loopback (kecuali
`REKAMIND_INSECURE_NO_AUTH=true`, yang sengaja dibuat canggung diketik).

Pasang di belakang reverse proxy HTTPS. Cookie sesi bertanda `Secure` hanya bila `PUBLIC_URL` https.

## 3. Cara kerjanya (ringkas)

- Authorization code + **PKCE** (S256) + `state` + `nonce`. Server (confidential client) yang menukar kode.
- ID token diverifikasi ketat: tanda tangan RS256 dari JWKS penerbit, `iss`, `aud`, `exp`, `iat`, `nonce`,
  `azp`, dan `email_verified` harus `true`.
- Akun diidentifikasi dengan klaim **`sub`**, bukan email, sehingga email Google yang didaur ulang tidak
  mewarisi data pemilik lama. Pengguna yang diundang (belum punya `sub`) dikaitkan pada login pertamanya.
  Catatan: ini kepercayaan pada penggunaan pertama (TOFU); undang hanya email yang Anda yakin milik orangnya.
- Sesi: id acak `rks_…`; hanya hash SHA-256 yang disimpan. Cookie `rk_session` (HttpOnly, SameSite=Lax).
  Percobaan login terikat ke cookie `rk_flow` (anti login-CSRF) dan sekali pakai. Request yang mengubah data
  lewat cookie diperiksa `Origin`. Rate limit pada login. Menonaktifkan pengguna mencabut semua sesinya.
- **Aplikasi desktop (mode server)**: membuka browser sistem, server mengembalikan kode sekali-pakai ke
  `http://127.0.0.1:<port>`, aplikasi menukarnya dengan verifier PKCE miliknya, lalu menyimpan token sesi di
  penyimpanan kredensial OS (Windows Credential Manager / Secret Service). Aplikasi tidak pernah melihat
  rahasia Google.
- **Mode lokal** (backend di laptop yang sama): tidak ada login Google; backend hanya mendengarkan loopback dan
  dilindungi rahasia acak per peluncuran yang diketahui aplikasi desktop saja.
- Alat baris perintah: `rekamind-rec login --server URL --print-token`.

## 4. Yang sudah terbukti dan yang belum

Terbukti (otomatis, terhadap IdP tiruan yang menandatangani token RS256 sungguhan lewat HTTP): seluruh alur
login, penolakan token/klaim yang salah, isolasi data antar pengguna pada **setiap rute API** (tes inventori
rute gagal bila ada rute baru tanpa aturan kepemilikan), panel admin, login desktop lintas proses.

**Belum terbukti**: Google asli (tidak terjangkau dari lingkungan pengembangan; perilaku consent screen,
verifikasi aplikasi, dan format token terbaru perlu dicoba sekali di server Anda) dan penyimpanan kredensial
OS di Windows. Coba login pertama Anda sebelum mengandalkannya.

## Rencana lanjutan

- Opsi login OAuth lain (mis. IdP kampus) bisa ditambahkan nanti sebagai penyedia kedua; saat ini hanya Google.
- Kredensial layanan terpisah untuk worker GPU jarak jauh belum ada.

## Penghapusan data

Hapus di UI = pindah ke tong sampah (bisa diurungkan 10 detik, dan tetap pulih lewat API). Data benar-benar
dihapus (audio di disk/S3, transkrip, task, peserta) lewat **Hapus permanen** atau otomatis setelah
`REKAMIND_TRASH_DAYS` hari (bawaan 30; 0 = simpan selamanya). Rapat yang sedang diproses tidak bisa dihapus permanen (409).
