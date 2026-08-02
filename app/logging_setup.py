import logging
from pathlib import Path

from app.settings_store import config_dir


def configure_logging(log_dir: Path | None = None) -> None:
    """File + console logging so a crash's last actions survive even if the
    console window itself force-closes before anyone can copy the text.

    Defaults to config_dir()/"logs" (%LOCALAPPDATA%\\MeetingRecorder\\logs),
    not a CWD-relative "./logs" -- a packaged install's shortcut can have its
    working directory anywhere (e.g. C:\\Program Files\\...), where a
    non-admin user has no write access and this would crash silently before
    any window appears (console=False, see MeetingRecorder.spec)."""
    if log_dir is None:
        log_dir = config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
