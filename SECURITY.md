🌐 **English** · [Bahasa Indonesia](SECURITY.id.md)

# Security

Report security vulnerabilities **privately** through GitHub Security Advisories (the *Security* tab → *Report a
vulnerability*) in this repo, not through a public issue. Include reproduction steps and the version.

Main scope: authentication/authorization (`server/rekamind_server/auth`), data isolation between users, audio
uploads, and token storage in the desktop app. The threat model and known limitations are in
`docs/AUTH.md`.

Do not put secrets (Google client secret, tokens, `.env`) in commits, issues, or logs.
