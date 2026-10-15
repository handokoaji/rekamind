🌐 [English](INTEGRATIONS.md) · **Bahasa Indonesia**

# Ekspor dan integrasi task

## Ekspor rapat (Word, Markdown, JSON)

Tombol **Ekspor** di halaman rapat (setelah rapat diproses). Isi: judul, tanggal (dengan zona waktu), peserta, ringkasan,
keputusan, jalannya rapat, task, dan transkrip (opsional). Task yang **belum dikonfirmasi** tidak ikut kecuali Anda
mencentangnya, dan di berkas ditandai sebagai "Disarankan (belum ditinjau)".

Lewat API: `GET /api/meetings/{id}/export?format=docx|md|json&transcript=true|false&tasks=confirmed|all`.
Hak akses sama dengan rute lain: hanya pemilik rapat (atau super admin). JSON memakai skema `rekamind.meeting/v1`
dengan `tasks_schema: rekamind.tasks/v1`.

## Zona waktu

Bawaan **WIB** (`Asia/Jakarta`). Ubah dengan `REKAMIND_TIMEZONE` (`Asia/Makassar` = WITA, `Asia/Jayapura` = WIT, `UTC`, dll.).
Zona ini dipakai untuk: menerjemahkan "besok"/"Jumat depan" menjadi tanggal (memakai tanggal **lokal** rapat, bukan tanggal UTC),
jam di berkas ekspor, dan tampilan bawaan di UI. Di Pengaturan, tiap perangkat boleh memilih zona tampilan sendiri.

## Mengirim task ke sistem lain

Pengaturan -> **Integrasi task** -> Tambah. Lalu di tab **Task**, pilih tujuan dan tekan **Kirim**.

Aturan yang tidak bisa dilanggar:
- **Hanya task yang sudah Anda konfirmasi**, dan **hanya saat Anda menekan Kirim**. Mengonfirmasi tidak mengirim apa pun.
- Task dikirim **sekali**: mengirim lagi memperbarui isu yang sama (disimpan di `task_links`), dan task yang tidak berubah dilewati.
  Bila isu dihapus di sisi tujuan, task dikirim ulang sebagai isu baru.
- Integrasi milik pengguna yang membuatnya. Super admin pun tidak bisa memakai atau membaca token orang lain.
- Token disimpan **terenkripsi** (Fernet) dan tidak pernah dikirim balik ke UI.

### Kunci enkripsi
- Aplikasi desktop dan mode lokal: kunci acak dibuat otomatis di folder data (`secret.key`).
- Server bersama: wajib `REKAMIND_SECRET_KEY` (minimal 32 karakter acak):
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Tanpa itu halaman integrasi menjelaskan alasannya dan menolak
  menyimpan token. Mengganti kunci membuat token lama tidak terbaca (simpan ulang).

### GitHub Issues
Repo `pemilik/nama`, token (fine-grained dengan izin *Issues: read and write*, atau classic dengan `repo`).
GitHub Enterprise: isi alamat API server Anda. Pemetaan PIC: `Nama yang diucapkan = username GitHub`; yang tidak dipetakan
dikirim tanpa assignee (nama tetap tertulis di deskripsi). Tenggat dan estimasi ditulis di deskripsi (GitHub Issues tidak punya kolom tenggat).

### GitLab Issues
Proyek (`grup/sub/proyek` atau ID angka), token (Personal/Project Access Token dengan scope `api`), alamat server untuk GitLab sendiri.
Pemetaan PIC: `Nama = ID pengguna GitLab`. Tenggat masuk ke `due_date`, estimasi ke *time estimate*, label sesuai konfigurasi.

### Webhook
Cocok untuk task manager buatan sendiri, Zapier, n8n, atau Make (yang kemudian meneruskan ke Trello/Asana/ClickUp).
Rekamind mengirim `POST` JSON `rekamind.task/v1` dengan header:

| Header | Isi |
|---|---|
| `X-Rekamind-Event` | `task.created`, `task.updated`, atau `ping` |
| `X-Rekamind-Timestamp` | detik Unix |
| `X-Rekamind-Signature` | `sha256=` + HMAC-SHA256 atas `"{timestamp}.{body}"` dengan rahasia Anda |
| `Idempotency-Key` | `{id task}:{hash isi}`: kirim ulang yang sama = kunci yang sama |
| `X-Rekamind-Delivery` | id unik pengiriman |

Verifikasi di penerima (Python):
```python
import hmac, hashlib, time
def valid(secret, ts, body: bytes, header):
    if abs(time.time() - int(ts)) > 300: return False          # tolak replay lama
    want = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)
```
Penerima harus menjawab 2xx. Rekamind mencoba ulang 429/502/503/504 (menghormati `Retry-After`), dan **tidak mengikuti redirect**.

### Keamanan alamat tujuan
Alamat adalah masukan pengguna, jadi di **server bersama** hanya `https://` ke alamat publik yang diterima (tanpa 127.0.0.1,
10.x, 169.254.x, `localhost`): mencegah server dipakai memindai jaringan internal (SSRF). Administrator bisa mengizinkan alamat privat
(mis. GitLab di intranet) dengan `REKAMIND_INTEGRATIONS_ALLOW_PRIVATE=true`. Mode desktop/lokal (satu pengguna) mengizinkannya.
Batasan yang diketahui: DNS diperiksa sebelum permintaan, bukan di soket (celah DNS-rebinding kecil bila penyerang mengendalikan DNS).

## Status pengujian (jujur)
Terbukti otomatis: tes dengan server HTTP tiruan untuk GitHub, GitLab, dan webhook (isi permintaan, header, tanda tangan, idempotensi,
kegagalan per task, token ditolak, 429, redirect, kepemilikan), serta E2E browser nyata ke penerima webhook sungguhan.
**Belum teruji terhadap GitHub, GitLab, atau layanan lain yang asli.** Detail API (nama field, header versi, kode status) saya tulis dari
dokumentasi yang saya ingat dan perlu dicocokkan sekali dengan akun asli: buat repo uji, tombol "Uji integrasi", lalu kirim satu task.

## Rencana berikutnya
Trello, Asana, dan ClickUp bisa lewat webhook + Zapier/n8n sekarang; adaptor langsung ditambah bila ada kebutuhan nyata.
Task manager buatan sendiri: kirim spesifikasi API-nya dan adaptor khusus ditulis (antarmukanya `create/update/test` di `integrations.py`).
Sinkron status dua arah belum dikerjakan (butuh webhook masuk dan penyelesaian konflik).
