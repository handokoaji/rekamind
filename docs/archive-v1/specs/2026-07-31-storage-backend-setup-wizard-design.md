# Meeting Recorder — Storage Backend Abstraction & First-Run Setup Wizard Design Spec

Date: 2026-07-31

## 1. Purpose

App ini akan didistribusikan sebagai `.exe` terinstall ke rekan-rekan kantor,
bukan lagi dijalankan dari source code oleh satu orang. Sekarang app
mewajibkan Postgres (5 env var + `DATABASE_URL`) dan tidak punya UI setting
sama sekali — setiap instalasi baru butuh orang itu sendiri yang edit `.env`
manual dan (kalau mau data terpisah dari server Postgres pemilik repo) juga
harus install & kelola Postgres sendiri. Ini tidak cocok untuk distribusi ke
non-technical user.

Spec ini menambahkan:
- **Backend penyimpanan kedua (SQLite)**, jadi default zero-config untuk
  instalasi baru — tanpa server terpisah, data otomatis lokal ke laptop
  masing-masing.
- **Wizard first-run** yang muncul sebelum window utama kalau belum ada
  konfigurasi tersimpan, plus menu **Pengaturan** untuk membukanya lagi
  kapan saja.

Di luar cakupan spec ini (dibahas di spec terpisah): `device_id` untuk
multi-perangkat, sinkronisasi file rekaman/docx ke MinIO, deteksi/fallback
GPU-CPU, packaging jadi `.exe`, dan durasi meeting otomatis.

## 2. Prinsip Utama

- **SQLite adalah default, Postgres adalah "Pengaturan Lanjutan".** Satu
  codebase, satu wizard, dua mode — bukan dua build terpisah.
- **Zero-config harus benar-benar zero-config.** Klik "Simpan & Mulai" tanpa
  isi apa pun harus langsung bisa rekam + transkrip.
- **API key (Groq, HF) opsional, bisa dilewati.** Fitur yang butuh key
  nonaktif dengan pesan jelas sampai diisi — bukan memblokir seluruh app.
- **Mode development (checkout source + `.env`) tidak berubah sama sekali.**
  Wizard hanya relevan untuk instalasi `.exe` yang belum punya config.
- **Ganti backend = mulai bersih, bukan migrasi otomatis.** Data lama di
  backend sebelumnya tetap ada di tempatnya, tidak dipindah otomatis — di
  luar cakupan v1.

## 3. Precedence Config (dev vs terpaket)

```
main() startup:
  ada .env di root repo?
    ya  -> pakai .env seperti sekarang (mode dev, TIDAK BERUBAH)
    tidak ->
      ada %LOCALAPPDATA%\MeetingRecorder\config.json ?
        ya  -> load dari situ, lanjut startup normal
        tidak -> tampilkan wizard SEBELUM window utama
                 -> user isi -> tulis config.json -> lanjut startup normal
```

`.env` tetap satu-satunya sumber config untuk siapa pun yang menjalankan dari
source (termasuk seluruh test suite yang ada) — tidak tersentuh oleh
perubahan ini sama sekali.

## 4. Perubahan `Settings` (`app/config.py`)

Sekarang `postgres_host/port/user/password/db` WAJIB diisi dan `database_url`
adalah field terpisah yang isinya duplikat dari kelima field itu. Disederhanakan:

```python
class Settings(BaseSettings):
    storage_backend: Literal["sqlite", "postgres"] = "sqlite"

    # Hanya wajib kalau storage_backend == "postgres"
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None

    groq_api_key: str = ""
    hf_token: str = ""
    asr_backend_override: str = ""

    @property
    def database_url(self) -> str:
        if self.storage_backend == "sqlite":
            return f"sqlite+aiosqlite:///{sqlite_db_path()}"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
```

`database_url` sebagai raw string dihapus dari `.env.example`/config sumber —
sekarang selalu dihitung, satu sumber kebenaran. `recordings_dir` tetap ada
tapi defaultnya berubah (lihat §6), tidak lagi field yang diisi user.

`app/storage/db.py::make_engine` sudah punya percabangan
`database_url.startswith("sqlite")` untuk `NullPool` — tidak perlu berubah.

## 5. `app/settings_store.py` (baru)

Modul kecil, tanggung jawab tunggal: baca/tulis `config.json` di
`%LOCALAPPDATA%\MeetingRecorder\`.

```python
def config_dir() -> Path: ...          # %LOCALAPPDATA%\MeetingRecorder
def config_path() -> Path: ...         # config_dir() / "config.json"
def load_packaged_config() -> dict | None: ...   # None kalau belum ada file
def save_packaged_config(data: dict) -> None: ...
def is_dev_mode() -> bool: ...         # True kalau .env ada di root repo
```

`get_settings()` di `app/config.py` dimodifikasi: kalau `is_dev_mode()` →
perilaku sekarang (baca `.env`) tidak berubah; kalau tidak, isi
`pydantic-settings` dari `load_packaged_config()` (atau `{}` kalau `None`,
yang lalu jatuh ke default `storage_backend="sqlite"` seperti diharapkan).

## 6. Lokasi File Default

```
%LOCALAPPDATA%\MeetingRecorder\
  config.json          # settings (§5)
  meeting.db           # SQLite database (kalau storage_backend == "sqlite")
  recordings\          # WAV + docx per meeting (recordings_dir baru, ganti "./recordings")
```

Tidak ada file-picker di wizard (sudah diputuskan) — lokasi ini tetap, tidak
bisa diubah dari UI di v1.

## 7. Wizard UI (`app/ui/setup_wizard.py`, baru)

Satu window Tk modal, field:

1. **Storage** — radio button `SQLite (default)` / `Postgres (lanjutan)`.
   Pilih Postgres membuka 5 field (host, port, user, password, db) yang
   disembunyikan secara default.
2. **GROQ_API_KEY** — text field + tombol **Lewati** di sebelahnya (fokus
   pindah tanpa mewajibkan isi).
3. **HF_TOKEN** — sama seperti di atas.
4. Tombol **Simpan & Mulai**.

Validasi saat submit:
- Storage = SQLite → tidak ada pengecekan, selalu valid (tinggal buat file).
- Storage = Postgres → coba `engine.connect()` sekali (async, dengan timeout
  singkat) sebelum menulis config; gagal → tampilkan pesan error inline di
  wizard, tidak menutup window, config TIDAK ditulis.
- Submit sukses → `save_packaged_config(...)`, tutup wizard, lanjut ke
  `main()` seperti startup normal (init_db, dst).

Dipanggil dari `main()` sebelum `MainWindow` dibuat, kalau
`load_packaged_config() is None` dan bukan dev mode.

## 8. Menu "Pengaturan" (reopen wizard)

`MainWindow` dapat satu tombol/menu baru "Pengaturan" (sejajar tombol
"Meeting Baru"/"Riwayat" yang sudah ada) yang membuka window wizard yang
sama, field terisi nilai `Settings` saat ini. Simpan → tulis ulang
`config.json`, tampilkan pesan "Restart aplikasi untuk menerapkan
perubahan." (tidak ada live-swap koneksi DB di tengah sesi — sengaja
disederhanakan, App restart itu murah/cepat untuk app ini).

## 9. Penanganan Error Saat Startup Normal

Config sudah ada (bukan first-run) tapi `init_db()` gagal (mis. Postgres
server yang tersimpan di config sekarang mati) → dialog error dengan tombol
**Buka Pengaturan** (membuka wizard §7/§8), bukan crash tanpa penjelasan.

## 10. Testing

- `tests/test_settings_store.py` (baru): round-trip tulis/baca
  `config.json` pakai `tmp_path` sebagai `%LOCALAPPDATA%` palsu
  (`monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))`); `is_dev_mode()`
  true/false tergantung `.env` ada/tidak.
- `tests/test_config.py`: `Settings().database_url` menghasilkan string
  SQLite yang benar untuk `storage_backend="sqlite"` dan string asyncpg yang
  benar untuk `"postgres"`; Postgres fields boleh `None` saat
  `storage_backend="sqlite"` (tidak raise).
- `tests/ui/test_setup_wizard.py` (baru, ikut pola `_tk_available()` yang
  sudah ada di `tests/ui/`): render field, expander Postgres cuma muncul
  saat radio Postgres dipilih, tombol Lewati mengosongkan field key tanpa
  block submit, submit SQLite memanggil `save_packaged_config` dengan data
  yang benar tanpa mencoba konek DB apa pun.
- Tidak butuh Postgres/hardware asli untuk semua test di atas (konsisten
  dengan konvensi test suite yang ada).

## 11. Di Luar Cakupan (v1)

- Migrasi data otomatis saat ganti backend.
- File-picker lokasi database/rekaman custom.
- Live-reload config tanpa restart app.
- `device_id`, sinkron file ke MinIO, deteksi GPU/CPU, packaging `.exe`,
  durasi meeting otomatis — masing-masing spec terpisah.
