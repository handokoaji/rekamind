"""Entry point of the frozen desktop backend (PyInstaller). Not used by the Docker image or pip installs.

    rekamind-backend                      run the API (+ in-process worker), configured by REKAMIND_* env
    rekamind-backend engines status       JSON: is the engine pack installed?
    rekamind-backend engines install cpu|cuda [--diarize]
    rekamind-backend engines warmup [model]
"""
import logging
import multiprocessing
import sys


def _ensure_stdio() -> None:
    # Started without a console (Windows GUI parent): the std streams are None and logging would crash.
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def run() -> int:
    _ensure_stdio()
    multiprocessing.freeze_support()  # pyannote/torch may spawn workers; harmless otherwise
    from rekamind_server import enginepack

    if len(sys.argv) > 1 and sys.argv[1] == "engines":
        return enginepack.main(sys.argv[2:])
    enginepack.activate()  # engines are imported lazily, after this
    from rekamind_server import parentwatch

    parentwatch.watch_from_env()  # die with the desktop app instead of lingering after a crash
    import uvicorn

    from rekamind_server.api import create_app
    from rekamind_server.config import Settings

    s = Settings()
    app = create_app(s)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=s.host, port=s.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
