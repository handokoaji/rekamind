# Meeting Recorder — Device Identity (`device_id`) Design Spec

Date: 2026-07-31

## 1. Purpose

Begitu app didistribusikan ke banyak orang/perangkat (lihat
[storage backend spec](2026-07-31-storage-backend-setup-wizard-design.md)),
data dari beberapa laptop bisa berakhir di satu tempat yang sama — baik
lewat Postgres terpusat yang dipakai bersama, maupun (nanti) lewat sinkron
file ke MinIO. Tanpa penanda, tidak ada cara tahu meeting mana berasal dari
perangkat mana.

Spec ini menambahkan identitas perangkat yang stabil, di-generate sekali per
instalasi, dicap ke setiap meeting yang dibuat dari perangkat itu.

## 2. Prinsip Utama

- **Satu ID stabil per instalasi**, bukan per hardware — di-generate acak
  sekali, disimpan di config lokal yang sama dengan spec storage backend.
  Install ulang app = ID baru; ini sudah cukup, tidak perlu ID yang bertahan
  lintas install-ulang OS.
- **Nama yang manusiawi terpisah dari ID.** UUID untuk keunikan, label teks
  untuk ditampilkan — supaya Riwayat menunjukkan "Laptop Budi", bukan string
  acak.
- **Berlaku sama di semua backend.** Tidak ada percabangan SQLite vs
  Postgres — device_id dicap ke setiap meeting apa pun backend-nya, supaya
  konsisten kalau data digabung nanti.
- **Numpang di infrastruktur yang sudah ada.** Tidak ada tabel/halaman baru
  — nempel di `config.json` dan wizard/menu Pengaturan dari spec storage
  backend.

## 3. Perubahan Skema (`app/storage/models.py`)

```python
class Meeting(Base):
    ...
    device_id: Mapped[str | None] = mapped_column(default=None)
    device_label: Mapped[str | None] = mapped_column(default=None)
```

Nullable: meeting lama (sebelum migrasi ini) punya nilai `NULL` di kedua
kolom, ditangani di UI (§6), bukan di-backfill.

## 4. Perubahan `Settings` / `settings_store` (dari spec storage backend)

```python
class Settings(BaseSettings):
    ...
    device_id: str = ""     # UUID string, diisi wizard first-run
    device_label: str = ""  # default socket.gethostname(), editable
```

`settings_store.save_packaged_config()` men-generate `device_id` (`uuid.uuid4().hex`)
HANYA kalau belum ada nilai di config lama yang sedang di-load ulang (mis.
saat user buka Pengaturan dan simpan lagi) — sekali dibuat, dipertahankan
selamanya untuk instalasi itu, tidak pernah diganti otomatis.

## 5. Perubahan Wizard (`app/ui/setup_wizard.py`)

Satu field baru: **"Nama perangkat"**, text field, prefill
`socket.gethostname()`, editable, wajib tidak kosong (fallback ke hostname
kalau dikosongkan). Muncul di wizard first-run maupun saat dibuka ulang
lewat menu Pengaturan — field yang sama, bukan UI terpisah.

## 6. Perubahan Controller & Repository

`RecorderController.start_meeting()` membaca `device_id`/`device_label` dari
`Settings` yang di-inject, meneruskannya ke `repo.create_meeting(...)`
sebagai dua argumen baru (default `None`, supaya test lama yang tidak
mengisi ini tetap jalan tanpa perubahan).

## 7. Perubahan UI Riwayat (`app/ui/history_view.py`)

Kolom baru di `Treeview`: `Judul | Tanggal | Status | Perangkat`.
`device_label` yang `NULL` (meeting lama) ditampilkan sebagai
**"Tidak diketahui"**.

## 8. Testing

- `test_repository.py`: `create_meeting(..., device_id=..., device_label=...)`
  menyimpan kedua field; meeting dibuat tanpa argumen ini tetap `NULL` (tidak
  ada breaking change untuk test lama).
- `test_controller.py`: `start_meeting()` meneruskan `device_id`/`device_label`
  dari `Settings` ke `create_meeting`.
- `test_settings_store.py` (dari spec storage backend, diperluas): device_id
  di-generate sekali dan **dipertahankan** across `save_packaged_config()`
  berikutnya (tidak berubah tiap kali Pengaturan disimpan ulang).
- `test_history_view.py`: kolom Perangkat menampilkan `device_label`, dan
  "Tidak diketahui" untuk meeting dengan `device_label=None`.

## 9. Di Luar Cakupan (v1)

- Tabel `Device` normalized / manajemen device (rename, hapus, dst. di luar
  edit label lewat Pengaturan).
- ID berbasis hardware (MAC address, motherboard serial) — dianggap
  berlebihan dan berisiko privasi untuk kebutuhan ini.
- Filter/grouping Riwayat berdasarkan perangkat — tampil sebagai kolom saja
  di v1, tidak ada UI filter.
