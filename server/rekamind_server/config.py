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
    whisper_device: str = "auto"  # auto | cuda | cpu
    whisper_compute_type: str = "auto"
    glossary: str = ""  # comma/newline separated names and jargon, fed to Whisper as a prompt
    # Diarization: none | pyannote
    diarizer: str = "none"
    hf_token: str = ""
    # Summaries / tasks: any OpenAI-compatible endpoint (Groq, OpenAI, Ollama, vLLM)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"

    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite+aiosqlite:///{self.data_dir / 'rekamind.db'}"
