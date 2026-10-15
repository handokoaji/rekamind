__version__ = "0.4.0b4"


def build_id() -> str:
    """The commit this build was made from, written by scripts/build_desktop.py (or "dev" when run from a checkout).
    Every build of a version shares the version number, so this is what tells two installers apart."""
    try:
        from ._buildinfo import COMMIT

        return COMMIT
    except ImportError:
        return "dev"
