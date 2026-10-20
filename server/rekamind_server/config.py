from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REKAMIND_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".rekamind")
    # Empty means "sqlite file inside data_dir"; set to a postgresql+asyncpg:// URL for a shared server.
    database_url: str = ""
    # Local mode runs the worker inside the API process; a dedicated GPU server
    # can set this to false and run `python -m rekamind_server.worker` instead.
    worker_inprocess: bool = True
    worker_poll_seconds: float = 1.0
    language: str = "id"
    # The zone meetings are read in (dates for deadlines, the times in exports). Default WIB.
    timezone: str = "Asia/Jakarta"
    # Deleted meetings stay recoverable this long, then audio and data are removed for good (0 = keep forever).
    trash_days: int = 30

    # --- Access control ----------------------------------------------------------------------
    # google      : multi-user, "Sign in with Google" using YOUR OWN Google OAuth client (default)
    # local_token : single user on this machine, a per-launch secret (used by the desktop app)
    # none        : no authentication; loopback only (development and tests)
    auth: str = "google"
    host: str = "127.0.0.1"
    port: int = 8787
    insecure_no_auth: bool = False  # explicit opt-in to run `auth=none` on a non-loopback address
    local_token: str = ""
    # Public address users reach this server at, e.g. https://rekamind.kantor.id. Google redirects back here.
    public_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where tokens are verified. Only ever changed to point tests at a fake identity provider.
    oidc_issuer: str = "https://accounts.google.com"
    # Comma-separated verified Google emails with full control of the server (bootstrapped on first login).
    superadmins: str = ""
    # Who else may sign in. "allowlist": the emails/domains below plus anyone a super admin invites.
    # "open": any verified Google account (only sensible on a private network).
    signup: str = "allowlist"
    allowed_emails: str = ""
    allowed_domains: str = ""
    session_days: int = 14
    # Encrypts third-party tokens stored for integrations (>= 32 random characters). Optional in single-user modes.
    secret_key: str = ""
    # Integrations may reach private/loopback addresses (a self-hosted GitLab, a local webhook). Off on a shared
    # server by default: otherwise any user could make the server probe its own network (SSRF).
    integrations_allow_private: bool = False
    desktop_session_days: int = 30
    max_upload_mb: int = 4096
    # Built SPA to serve at "/" (the Docker image sets this); empty = API only.
    web_dir: str = ""
    # Only needed when a UI is served from a different origin than the API (e.g. a desktop shell
    # talking to a remote backend). Same-origin deployments leave this empty.
    cors_origins: str = ""
    # Audio storage: "local" (under data_dir) or "s3" (MinIO, SeaweedFS, AWS...)
    storage: str = "local"
    s3_endpoint_url: str = ""
    s3_bucket: str = "rekamind"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_prefix: str = ""
    s3_path_style: bool = True  # MinIO and SeaweedFS need path-style addressing
    s3_create_bucket: bool = True
    # "fake" = deterministic stub engines for UI development. Real engines (cuda, vulkan,
    # openvino, remote) are added behind the same Engines contract; "none" refuses to process.
    engines: str = "none"
    # ASR
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"  # auto | cuda | cpu | intel (OpenVINO) | vulkan (whisper.cpp; AMD/any Vulkan GPU); "auto" follows the installed engine pack
    whispercpp_quant: str = "q5_0"  # vulkan engine: model quantisation (q5_0 ~ 1 GB for large-v3); "none" = full precision
    vulkan_device: int = 0  # vulkan engine: which Vulkan device (whisper-cli -dev); 0 is usually the integrated GPU on a laptop with one
    openvino_device: str = "GPU"  # OpenVINO device for "intel": GPU (iGPU) | CPU | AUTO; falls back to CPU if the GPU cannot load it
    whisper_compute_type: str = "auto"
    glossary: str = ""  # comma/newline separated names and jargon, fed to Whisper as a prompt
    # Diarization: none | pyannote
    diarizer: str = "none"
    hf_token: str = ""
    # Model downloads slower than this (MB/s, over 10 s) are dropped and retried on a new connection; 0 = never.
    hf_min_mbps: float = 0.5
    # Summaries / tasks: any OpenAI-compatible endpoint (Groq, OpenAI, Ollama, vLLM)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    llm_chunk_chars: int = 12000  # transcript characters per request; lower it for small per-minute token caps

    @staticmethod
    def _csv(v: str) -> set[str]:
        return {x.strip().lower() for x in v.replace("\n", ",").split(",") if x.strip()}

    @property
    def superadmin_emails(self) -> set[str]:
        return self._csv(self.superadmins)

    @property
    def allowed_email_set(self) -> set[str]:
        return self._csv(self.allowed_emails)

    @property
    def allowed_domain_set(self) -> set[str]:
        return {d.lstrip("@") for d in self._csv(self.allowed_domains)}

    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'rekamind.db'}"
