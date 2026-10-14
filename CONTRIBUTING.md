# Berkontribusi

Rekamind berlisensi MIT: siapa pun boleh memakai, memasang sendiri, dan menggandakannya. Perubahan ke repo
ini masuk lewat pull request yang ditinjau maintainer.

Sebelum membuka PR, jalankan yang relevan:

```bash
cd server && ruff check . && pytest -q
cd web && npx tsc -b --noEmit && npx vitest run
cd recorder && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

Aturan yang tidak boleh dilanggar:
- Rute API baru wajib memakai pengguna saat ini dan memfilter berdasarkan pemilik. Tes inventori rute di
  `server/tests/test_auth.py` akan gagal bila lupa.
- Perekam harus tetap ringan: jangan menambah kerja berat atau dependensi besar di `recorder/`.
- Jangan menambah kredensial bawaan atau rahasia ke repo.
