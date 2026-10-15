🌐 [English](SECURITY.md) · **Bahasa Indonesia**

# Keamanan

Laporkan celah keamanan **secara privat** lewat GitHub Security Advisories (tab *Security* → *Report a
vulnerability*) di repo ini, bukan lewat issue publik. Sertakan langkah reproduksi dan versi.

Cakupan utama: autentikasi/otorisasi (`server/rekamind_server/auth`), isolasi data antar pengguna, unggahan
audio, dan penyimpanan token di aplikasi desktop. Model ancaman dan batasan yang diketahui ada di
`docs/AUTH.id.md`.

Jangan memasukkan rahasia (client secret Google, token, `.env`) ke commit, issue, atau log.
