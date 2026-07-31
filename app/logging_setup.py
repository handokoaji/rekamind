import logging
from pathlib import Path


def configure_logging(log_dir: Path = Path("./logs")) -> None:
    """File + console logging so a crash's last actions survive even if the
    console window itself force-closes before anyone can copy the text."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "app.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
