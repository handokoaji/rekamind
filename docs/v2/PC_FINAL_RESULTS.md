# Hasil uji akhir di PC (Windows 11 + GTX 1080 Ti)

Tanggal: 2026-10-15. Commit: `ebc3f1c` (`v2/core-api`, di atas `5a19f65`). Penguji otomatis: Claude (sesi tanpa layar/telinga).
Status: bagian otomatis selesai; butir **[ANDA]** menunggu pengguna. Keputusan gerbang rilis di bawah: **NO-GO SEMENTARA**.

## Langkah 0

| Butir | Status | Bukti |
|---|---|---|
| Build installer | LULUS | `build_desktop.py` 4,3 mnt; `Rekamind_0.0.1_x64-setup.exe` 70,2 MiB |
| Smoke backend beku | LULUS | "Smoke test lulus.", **17** baris ok (Word, Markdown, WIB, enkripsi token, pip beku) |
| Pasang bersih di PC/VM tanpa Python/Rust [G1] | TIDAK DIUJI | PC ini punya Python, Rust, Node |
| SmartScreen/antivirus, ukuran terpasang, konsol berkedip [G14] | TIDAK DIUJI | pasang `/S` senyap, tidak diamati |

## Otomatis

| Butir | Status | Bukti |
|---|---|---|
| pytest server | LULUS | 203 lulus |
| vitest web | LULUS | 8 berkas, 71 tes |
| Playwright | LULUS | 23 lulus (1,0 mnt) |
| cargo `recorder` | LULUS | 70 tes, 0 gagal (`desktop\src-tauri`: 0 tes). Dokumen menyebut 93: selisih 23 belum dijelaskan (kemungkinan tes khusus Linux) |
| B11 bench | LULUS | `cuda`/`int8`, `peak_rss_mb` 1571, RTF 0,008 |
| B2 pack NVIDIA + diarisasi (pack sama dengan uji sebelumnya) | LULUS | `engines check`: ok, 1 GPU, ctranslate2 4.8.3, faster_whisper 1.2.1 setelah upgrade |
| C3/G10 pasang di atas versi lama tanpa uninstall | LULUS | sebelum/sesudah identik: pack 6,73 GB (`cuda`+diarize), DB 336 KB, 3 folder rekaman, cache model 2979 MB; app dan backend start, `/api/health` 200 |

## Sudah dibuktikan di sesi sebelumnya (laporan `PC_RETEST_RESULTS.md`, kode `5cb5c04`)

B4/B5/G6 sebagian: rapat 85 mnt selesai (1173 segmen, 4 pembicara, 9 task, 9x 429 pulih), `loading whisper large-v3 on cuda (int8)`,
VRAM 3,3-4,2 GB (puncak 5,3 GB saat diarisasi). B7 dan B8 belum terbukti pada kode terbaru (lihat di bawah).

## B8 / G8: backend stabil 30 menit

| Butir | Status | Bukti |
|---|---|---|
| B8/G8 tanpa startup/shutdown berulang | LULUS | 30,0 mnt (kode `ebc3f1c`, aplikasi dibuka 10:23, proses `rekamind.exe` hidup selama itu): 0 "Started server process" baru, 0 Traceback/ERROR/Shutting down, 129 baris log baru |
| `GET /api/health` wajar (~2/menit) | CATATAN | 120 permintaan = ±4/menit (sekali per 15 dtk), dua kali target "~2/menit". Bukan masalah (dulu 1764 dalam 20 dtk), tapi lebih rapat dari yang dokumen sebut |

Catatan: saya tidak memverifikasi bahwa jendela tetap terbuka (hanya proses UI yang hidup), dan tidak ada aksi pengguna selama 30 menit.
Temuan lama "backend restart sendiri 5x" (08:31-09:36) **tidak muncul lagi** pada kode terbaru dalam jendela ini; penyebab tidak saya verifikasi.

## Update: perubahan masuk setelah uji otomatis (10:5x WIB)

Saat mendorong hasil G8, GitHub menolak push (non-fast-forward) karena dua commit baru dari pihak lain:

| Commit | Isi |
|---|---|
| `cf51bb0` | `chore(release): v0.4.0-beta.1 pre-release, README rewrite, docs hygiene` |
| `0e8a42a` | `ci: fix recorder clippy (chunks_exact lint) and docker image build env` |

Keduanya tidak menyentuh `PC_FINAL_RESULTS.md`; digabung dengan **merge** (bukan rebase/force) menjadi `7385e8f`
supaya `origin` (GitLab UGM) tetap fast-forward. Kedua remote sekarang di `7385e8f`.

**Dampak pada keabsahan hasil:** perubahan itu 75 berkas (+992/-291), termasuk web (`AppShell.tsx`, `LoginScreen.tsx`,
`Logo.tsx`, `vite.config.ts`, `playwright.docs.config.ts`). Seluruh hasil otomatis di dokumen ini (build 70,2 MiB, smoke 17 ok,
pytest 203, vitest 71, Playwright 23, cargo 70, bench, C3, G8) berasal dari `ebc3f1c`, **bukan** dari `v0.4.0-beta.1`.
Bila uji akhir harus mengesahkan beta.1, build + smoke + tes otomatis perlu diulang dari `7385e8f`.

## Menunggu pengguna [ANDA]

A1-A7 (rekam >= 30 mnt jendela tertutup, putar WAV, cabut headset, mati paksa, rekaman berjalan, zona waktu Windows, sleep),
B3 (Batalkan), B6 (mic nyata), B9 (tutup jendela 12 mnt), C1 (Credential Manager), C2 (uninstall), C4-C6 (instance ganda, tray, `--hidden`),
D1-D8 (Task, pemutar bukti, scroll, Word, Markdown, JSON, zona waktu, tengah malam), E1-E2 (GitHub/GitLab asli), E4, H1-H3.

## Gerbang rilis (sementara)

| Gerbang | Status |
|---|---|
| G1 pasang bersih tanpa Python/Rust | TIDAK DIUJI |
| G2 mesin dari UI (CPU dan NVIDIA) | SEBAGIAN (NVIDIA lulus sebelumnya; CPU belum) |
| G3 rekam >= 30 mnt jendela tertutup | TIDAK DIUJI |
| G4 mati paksa, rekaman tidak hilang | TIDAK DIUJI |
| G5 rekaman berjalan tidak bisa dihapus | SEBAGIAN (tes otomatis lulus, manual belum) |
| G6 rapat >= 50 mnt, "Buat ulang ringkasan" | SEBAGIAN (rapat 85 mnt lulus; tombol belum terpicu) |
| G7 Word di Microsoft Word | TIDAK DIUJI |
| G8 backend stabil 30 mnt | LULUS (0 restart, 0 galat) |
| G9 kredensial setelah keluar | TIDAK DIUJI |
| G10 uninstall/install ulang | SEBAGIAN (pasang di atas lulus; uninstall bersih belum) |
| G11 GitHub/GitLab asli | TIDAK DIUJI |
| G12-G13 Google/Linux | TIDAK DIUJI (bukan lingkup sesi ini) |
| G14 SmartScreen | TIDAK DIUJI |
| G15 Task + pemutar + mic ME | TIDAK DIUJI |

**Keputusan: NO-GO sementara.** Beberapa gerbang WAJIB (G1, G3, G4, G7, G9, G15) belum diuji sama sekali.
