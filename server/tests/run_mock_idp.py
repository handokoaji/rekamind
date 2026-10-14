"""Run the fake identity provider as a real HTTP server (used by the browser end-to-end tests).

    python run_mock_idp.py --port 18971 --redirect http://127.0.0.1:18970/auth/callback
"""

import argparse

import uvicorn
from mock_idp import MockIdp

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18971)
    ap.add_argument("--redirect", required=True)
    a = ap.parse_args()
    idp = MockIdp(redirect_uri=a.redirect, issuer=f"http://127.0.0.1:{a.port}")
    uvicorn.run(idp.app, host="127.0.0.1", port=a.port, log_level="warning")
