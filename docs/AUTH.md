🌐 **English** · [Bahasa Indonesia](AUTH.id.md)

# Rekamind login and access rights

Rekamind is open source (AGPL-3.0-or-later). Anyone may install it on their own server. For that reason there are **no default
Google credentials**: each installer creates their own Google OAuth client and supplies it through
environment variables. Secrets are never in the repo, in the browser, or in the desktop app.

## Access rules

| Role | Allowed |
|---|---|
| **User** | Can only see and modify meetings, tasks, and participants **that they own**. Other people's data is answered with `404` (not `403`, so its existence does not leak). |
| **Super admin** | Everything: sees all meetings (the **"Semua pengguna"** (All users) button), invites/deactivates users, promotes/demotes roles. The initial list of super admins comes from `REKAMIND_SUPERADMINS`. The last active super admin cannot be demoted or deactivated. |

Who may create an account:
- `REKAMIND_SIGNUP=allowlist` (default): only emails in `REKAMIND_ALLOWED_EMAILS`, domains in `REKAMIND_ALLOWED_DOMAINS`, super admins, or those invited by a super admin.
- `REKAMIND_SIGNUP=open`: any Google account with a verified email. Only use this if you really want an open server.

## 1. Creating the Google OAuth client (once, by the installer)

> The steps in Google Cloud Console change over time and **I cannot verify them from this
> development environment** (Google hosts are blocked). Treat the menu names below as hints, and
> check them against Google's latest documentation.

1. Open Google Cloud Console, create a project, then set up the OAuth consent screen.
   For internal use within a Google Workspace organization choose the *Internal* type; otherwise *External*.
   The "Testing" status limits access to a list of test users and can make refresh tokens expire. That is
   not a problem here because Rekamind only requests the `openid email profile` scope and creates its own session.
2. Create credentials: *OAuth client ID*, type *Web application*.
3. **Authorized redirect URI** is filled in exactly as: `{REKAMIND_PUBLIC_URL}/auth/callback`
   (example `https://rekamind.kantor.id/auth/callback`).
4. Copy the Client ID and Client secret into the server env.

## 2. Server configuration

```env
REKAMIND_AUTH=google
REKAMIND_PUBLIC_URL=https://rekamind.kantor.id   # must be https (except localhost)
REKAMIND_GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
REKAMIND_GOOGLE_CLIENT_SECRET=xxxx
REKAMIND_SUPERADMINS=anda@kantor.id              # comma-separated
REKAMIND_SIGNUP=allowlist
REKAMIND_ALLOWED_DOMAINS=kantor.id
# optional: REKAMIND_ALLOWED_EMAILS, REKAMIND_SESSION_DAYS (14), REKAMIND_DESKTOP_SESSION_DAYS (30)
```

The server **refuses to start** if the configuration is unsafe: Google without client id/secret/public URL, a public URL
that is not https, an unknown `signup` value, or `REKAMIND_AUTH=none` on an address other than loopback (unless
`REKAMIND_INSECURE_NO_AUTH=true`, which is deliberately awkward to type).

Install it behind an HTTPS reverse proxy. The session cookie is marked `Secure` only if `PUBLIC_URL` is https.

## 3. How it works (summary)

- Authorization code + **PKCE** (S256) + `state` + `nonce`. The server (a confidential client) exchanges the code.
- The ID token is verified strictly: RS256 signature from the issuer's JWKS, `iss`, `aud`, `exp`, `iat`, `nonce`,
  `azp`, and `email_verified` must be `true`.
- Accounts are identified by the **`sub`** claim, not by email, so a recycled Google email does not
  inherit the previous owner's data. An invited user (who does not have a `sub` yet) is linked on their first login.
  Note: this is trust on first use (TOFU); only invite emails that you are sure belong to the person.
- Sessions: random id `rks_…`; only the SHA-256 hash is stored. Cookie `rk_session` (HttpOnly, SameSite=Lax).
  A login attempt is bound to the `rk_flow` cookie (anti login-CSRF) and is single-use. Requests that modify data
  via cookie are checked for `Origin`. Rate limit on login. Deactivating a user revokes all of their sessions.
- **Desktop app (server mode)**: opens the system browser, the server returns a single-use code to
  `http://127.0.0.1:<port>`, the app exchanges it with its own PKCE verifier, then stores the session token in the
  OS credential store (Windows Credential Manager / Secret Service). The app never sees the
  Google secret.
- **Local mode** (backend on the same laptop): no Google login; the backend only listens on loopback and is
  protected by a random per-launch secret known only to the desktop app.
- Command-line tool: `rekamind-rec login --server URL --print-token`.

## 4. What is proven and what is not

Proven (automated, against a fake IdP that signs real RS256 tokens over HTTP): the entire login flow,
rejection of wrong tokens/claims, data isolation between users on **every API route** (the route inventory test
fails if a new route has no ownership rule), the admin panel, cross-process desktop login.

**Not proven**: real Google (not reachable from the development environment; the consent screen behavior,
app verification, and the latest token format need to be tried once on your server) and the OS credential
store on Windows. Try your first login before relying on it.

## Future plans

- Other OAuth login options (e.g. a campus IdP) can be added later as a second provider; for now only Google.
- Separate service credentials for a remote GPU worker do not exist yet.

## Data deletion

Deleting in the UI = moving to the trash (undoable for 10 seconds, and still recoverable via the API). Data is actually
deleted (audio on disk/S3, transcripts, tasks, participants) through **Hapus permanen** (Delete permanently) or automatically after
`REKAMIND_TRASH_DAYS` days (default 30; 0 = keep forever). A meeting that is being processed cannot be permanently deleted (409).
