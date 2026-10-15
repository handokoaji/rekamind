🌐 **English** · [Bahasa Indonesia](API_KEYS.id.md)

# Getting a Hugging Face token and a Groq API key

Rekamind works on your computer, but two optional features need an account with an outside service:

| You want | You need | Where it is used |
|---|---|---|
| **Speaker separation** (who said what) | A **Hugging Face token** | Settings → *Token Hugging Face* |
| **Summary and tasks** written by AI | A **Groq API key** (or any OpenAI-compatible service) | Settings → *Kunci API ringkasan* |

Recording and transcription work **without** either. Both are free to create; they are only your own credentials, and
Rekamind stores them in the operating system's credential store (Windows Credential Manager), not in a settings file.

> Note: this is **Groq** (with a **Q**, an AI inference service), not "Grok" from xAI.

Website labels change from time to time. If a button is named slightly differently, look for the closest one.

---

## 1. Hugging Face token (speaker separation)

Speaker separation uses the `pyannote` models. They are *gated*: Hugging Face only lets accounts that accepted their terms download
them, and your token is how Rekamind proves it is you. There are **two steps**: accept the terms, then create the token.

### 1a. Create an account
1. Open <https://huggingface.co/join> and sign up (email, or sign in with Google/GitHub).
2. Confirm your email address from the message Hugging Face sends you.

### 1b. Accept the terms of the models (do this before creating the token)
Open each page below while signed in, read the short form, and press the button that accepts access
(usually **Agree and access repository**). Fill in the company/university and use case fields if asked.

1. <https://huggingface.co/pyannote/speaker-diarization-3.1>
2. <https://huggingface.co/pyannote/segmentation-3.0>

When it worked, the page shows the model files instead of the form ("You have been granted access to this model").

### 1c. Create the token
1. Open <https://huggingface.co/settings/tokens>.
2. Click **Create new token** (or **+ Create new token**).
3. Choose the type **Read**. If you use a *Fine-grained* token instead, enable
   *Read access to contents of all public gated repos you can access*.
4. Give it a name such as `rekamind`, then click **Create token**.
5. **Copy the token now** (it starts with `hf_`). Hugging Face shows it only once; if you lose it, create a new one.

### 1d. Give it to Rekamind
1. Open Rekamind → **Pengaturan** (Settings).
2. Make sure **Tempat pemrosesan** is *Komputer ini (GPU lokal)*.
3. Paste the token into **Token Hugging Face**, then click **Simpan** (Save) at the bottom of the page.
4. In the **Mesin transkripsi** panel keep **Sertakan pemisah pembicara** ticked, then click the install button for your hardware.
   The install button stays disabled until a token is saved; untick the box if you do not want speaker separation.
5. After the install, set **Pemisah pembicara** to **pyannote (perlu paket + token)** and click **Simpan** again.
6. Open a meeting and use **Proses ulang** (Process again). The transcript now lists the separate speakers.

---

## 2. Groq API key (summary and tasks)

The summary, decisions and task list are written by a language model. Rekamind talks to **any OpenAI-compatible service**;
**Groq** is only the default, not a requirement. If you already use another provider, skip to
[Using another OpenAI-compatible service](#using-another-openai-compatible-service).

### 2a. Create an account
1. Open <https://console.groq.com> and click **Sign up** (Google, GitHub or email).
2. Finish the sign-up. Groq has a free tier with usage limits; check the console for the current limits and prices.

### 2b. Create the key
1. In the console, open **API Keys** (left menu, or <https://console.groq.com/keys>).
2. Click **Create API Key**, give it a name such as `rekamind`, and confirm.
3. **Copy the key now** (it starts with `gsk_`). It is shown only once; if you lose it, create a new one.

### 2c. Give it to Rekamind
1. Open Rekamind → **Pengaturan** → **Pemrosesan di komputer ini**.
2. Check the defaults, which already point at Groq:
   - **Layanan ringkasan (OpenAI-compatible)**: `https://api.groq.com/openai/v1`
   - **Model ringkasan**: `openai/gpt-oss-120b` (use another model from the Groq console if this one is retired)
3. Paste the key into **Kunci API ringkasan**, then click **Simpan**.
4. Process a meeting (**Proses sekarang**). The **Ringkasan** and **Task** tabs fill in when it finishes.

> **Privacy:** to write the summary, the *text of the transcript* is sent to the service you chose. The audio is not.
> If that is not acceptable for your meetings, use a local OpenAI-compatible server such as Ollama and enter its address in
> **Layanan ringkasan**, or skip summaries.

---

## Using another OpenAI-compatible service

Any service that speaks the OpenAI chat API works. You only change three fields in **Pengaturan → Pemrosesan di komputer ini**
(the summary service fields, from the same screen as step 2c):

| Field | What to enter |
|---|---|
| **Layanan ringkasan (OpenAI-compatible)** | The service's *base URL* (usually ends in `/v1`) |
| **Model ringkasan** | The exact model name the service gives you |
| **Kunci API ringkasan** | The key from that service (leave empty if it needs none) |

Common examples (check each provider's documentation for current values):

| Service | Base URL | Key |
|---|---|---|
| Groq (default) | `https://api.groq.com/openai/v1` | `gsk_…` from console.groq.com |
| OpenAI | `https://api.openai.com/v1` | `sk-…` from platform.openai.com |
| Ollama on this computer | `http://localhost:11434/v1` | not needed |
| Any other server (vLLM, LM Studio, OpenRouter, your company's gateway…) | the URL it documents | as documented |

Use a model that follows instructions well and writes Indonesian; very small local models often produce poor summaries.
The model must return structured (JSON) answers; if summaries fail with a model you picked, try a larger one.

---

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The install button is greyed out with "Token Hugging Face wajib diisi" | No token saved yet. Paste it in **Token Hugging Face** and click **Simpan**, or untick speaker separation. |
| "Pemisah pembicara gagal …" in a meeting | The token is wrong, expired, or you did not accept the terms of **both** models in step 1b. Accept them, then **Proses ulang**. |
| Still one speaker after processing | **Pemisah pembicara** is still *Tanpa* (none). Set it to *pyannote* and save. |
| `401` / "invalid token" from the summary service | The Groq key is mistyped or revoked. Create a new key and paste it again. |
| `429` / "rate limit" | You hit the service's limit. Wait a minute and process again, or use another plan or model. |
| "Ringkasan gagal" with a model name | The model was renamed or retired. Pick a current one in the Groq console and put it in **Model ringkasan**. |

## Keeping your keys safe
- Treat both as passwords: do not post them in chats, screenshots, issues, or commits.
- If one leaks, **revoke it** on its website (Hugging Face → Access Tokens, Groq → API Keys) and create a new one.
- Rekamind never writes them to `settings.json`; to clear one, replace it in **Pengaturan** or delete the entry in the
  Windows Credential Manager.
