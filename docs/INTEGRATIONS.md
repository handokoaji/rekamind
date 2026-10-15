🌐 **English** · [Bahasa Indonesia](INTEGRATIONS.id.md)

# Task export and integrations

## Meeting export (Word, Markdown, JSON)

The **Ekspor** (Export) button on the meeting page (after the meeting has been processed). Contents: title, date (with time zone), participants, summary,
decisions, meeting flow, tasks, and transcript (optional). Tasks that are **not yet confirmed** are not included unless you
tick the option, and in the file they are marked "Disarankan (belum ditinjau)" (Suggested, not yet reviewed).

Via the API: `GET /api/meetings/{id}/export?format=docx|md|json&transcript=true|false&tasks=confirmed|all`.
Access rights are the same as other routes: only the meeting owner (or a super admin). JSON uses the schema `rekamind.meeting/v1`
with `tasks_schema: rekamind.tasks/v1`.

## Time zone

Default is **WIB** (`Asia/Jakarta`). Change it with `REKAMIND_TIMEZONE` (`Asia/Makassar` = WITA, `Asia/Jayapura` = WIT, `UTC`, etc.).
This zone is used for: translating "tomorrow"/"next Friday" into dates (using the meeting's **local** date, not the UTC date),
the times in exported files, and the default display in the UI. In **Pengaturan** (Settings), each device may choose its own display zone.

## Sending tasks to other systems

Pengaturan -> **Integrasi task** (Task integrations) -> **Tambah** (Add). Then in the **Task** tab, choose the destination and press **Kirim** (Send).

Rules that cannot be broken:
- **Only tasks you have confirmed**, and **only when you press Kirim**. Confirming does not send anything.
- A task is sent **once**: sending again updates the same issue (stored in `task_links`), and tasks that have not changed are skipped.
  If the issue is deleted on the destination side, the task is sent again as a new issue.
- An integration belongs to the user who created it. Not even a super admin can use or read another person's token.
- Tokens are stored **encrypted** (Fernet) and are never sent back to the UI.

### Encryption key
- Desktop app and local mode: a random key is created automatically in the data folder (`secret.key`).
- Shared server: `REKAMIND_SECRET_KEY` is required (at least 32 random characters):
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Without it the integrations page explains why and refuses to
  store tokens. Changing the key makes old tokens unreadable (save them again).

### GitHub Issues
Repo `owner/name`, token (fine-grained with the *Issues: read and write* permission, or classic with `repo`).
GitHub Enterprise: enter your server's API address. PIC mapping: `Spoken name = GitHub username`; unmapped names
are sent without an assignee (the name is still written in the description). Due date and estimate are written in the description (GitHub Issues has no due date field).

### GitLab Issues
Project (`group/sub/project` or numeric ID), token (Personal/Project Access Token with the `api` scope), server address for self-hosted GitLab.
PIC mapping: `Name = GitLab user ID`. The due date goes into `due_date`, the estimate into *time estimate*, labels as configured.

### Webhook
Suitable for a self-built task manager, Zapier, n8n, or Make (which then forwards to Trello/Asana/ClickUp).
Rekamind sends a JSON `POST` of `rekamind.task/v1` with these headers:

| Header | Contents |
|---|---|
| `X-Rekamind-Event` | `task.created`, `task.updated`, or `ping` |
| `X-Rekamind-Timestamp` | Unix seconds |
| `X-Rekamind-Signature` | `sha256=` + HMAC-SHA256 over `"{timestamp}.{body}"` with your secret |
| `Idempotency-Key` | `{task id}:{content hash}`: resending the same thing = the same key |
| `X-Rekamind-Delivery` | unique delivery id |

Verification at the receiver (Python):
```python
import hmac, hashlib, time
def valid(secret, ts, body: bytes, header):
    if abs(time.time() - int(ts)) > 300: return False          # reject old replays
    want = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)
```
The receiver must respond with 2xx. Rekamind retries 429/502/503/504 (honoring `Retry-After`), and **does not follow redirects**.

### Destination address security
The address is user input, so on a **shared server** only `https://` to public addresses is accepted (no 127.0.0.1,
10.x, 169.254.x, `localhost`): this prevents the server from being used to scan the internal network (SSRF). An administrator can allow private addresses
(e.g. GitLab on an intranet) with `REKAMIND_INTEGRATIONS_ALLOW_PRIVATE=true`. Desktop/local mode (single user) allows them.
Known limitation: DNS is checked before the request, not at the socket (a small DNS-rebinding gap if an attacker controls DNS).

## Test status (honest)
Proven automatically: tests with fake HTTP servers for GitHub, GitLab, and webhook (request body, headers, signature, idempotency,
per-task failure, rejected token, 429, redirect, ownership), plus a real-browser E2E against an actual webhook receiver.
**Not yet tested against real GitHub, GitLab, or other real services.** The API details (field names, version headers, status codes) were written from
documentation I remember and need to be checked once against a real account: create a test repo, the **Uji integrasi** (Test integration) button, then send one task.

## Next plans
Trello, Asana, and ClickUp can work via webhook + Zapier/n8n now; direct adapters will be added if there is a real need.
Self-built task manager: send its API specification and a custom adapter will be written (the interface is `create/update/test` in `integrations.py`).
Two-way status sync has not been done (it needs incoming webhooks and conflict resolution).
