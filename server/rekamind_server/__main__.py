import uvicorn

from .api import create_app
from .config import Settings

if __name__ == "__main__":
    # Host and port come from settings (REKAMIND_HOST / REKAMIND_PORT). The default is loopback; the
    # Docker image sets 0.0.0.0, which is only accepted together with REKAMIND_AUTH=google.
    s = Settings()
    app = create_app(s)  # validates the auth configuration and refuses to start if it is unsafe
    uvicorn.run(app, host=s.host, port=s.port, forwarded_allow_ips="*" if s.public_url.startswith("https://") else "127.0.0.1")
