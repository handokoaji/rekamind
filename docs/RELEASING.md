# Merilis

Rilis dibuat otomatis oleh `.github/workflows/release.yml` saat sebuah tag `v*` didorong.
Tag berakhiran `-alpha.N`, `-beta.N`, atau `-rc.N` menjadi **pre-release** di GitHub.

1. Samakan versi di semua berkas: `python scripts/set_version.py 0.4.0-beta.2`
   (Python memakai bentuk PEP 440 `0.4.0b2` secara otomatis; `--check` memverifikasi).
2. Tambahkan entri di `CHANGELOG.md` dan tulis `docs/release-notes/v0.4.0-beta.2.md` (jujur soal batasan).
3. Jalankan tes: `pytest server`, `cd web && npm test`, `cd recorder && cargo test`.
4. Commit, gabungkan ke `master`, lalu:
   ```bash
   git tag -a v0.4.0-beta.2 -m "Rekamind v0.4.0-beta.2"
   git push origin v0.4.0-beta.2
   ```
5. Workflow memverifikasi versi = tag, membangun installer Windows (NSIS) dan Linux (.deb, plus AppImage bila
   berhasil), menjalankan smoke test backend beku, membuat `SHA256SUMS.txt`, dan menerbitkan release.
   Bila satu job gagal, tidak ada yang terbit; perbaiki lalu jalankan ulang lewat *Actions → Release → Run workflow*
   (isi tag yang sama).
6. Unduh dan coba tiap installer di mesin bersih sebelum mengumumkan.

Ikon aplikasi dibuat dari `docs/assets/logo.svg` (`scripts/make_icons.mjs`); logo di UI, favicon, dan README memakai
bentuk yang sama.
Screenshot README: `cd web && npm run build && npx playwright test -c playwright.docs.config.ts`.

Penandatanganan kode (Windows Authenticode, GPG) belum dikonfigurasi; itu syarat sebelum rilis final.
