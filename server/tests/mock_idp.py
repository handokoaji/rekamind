"""A stand-in for Google's OpenID Connect endpoints that signs REAL RS256 tokens, so the code that
verifies them is exercised against genuine signatures (and genuinely forged ones), not mocks."""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

ISSUER = "https://idp.test"


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Key:
    def __init__(self, kid: str):
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())

    def jwk(self) -> dict:
        n = self.private.public_key().public_numbers()
        return {"kty": "RSA", "kid": self.kid, "use": "sig", "alg": "RS256", "n": _b64(n.n), "e": _b64(n.e)}


class MockIdp:
    def __init__(self, client_id="cid", client_secret="csecret", redirect_uri="http://127.0.0.1:8787/auth/callback", issuer=ISSUER):
        self.client_id, self.client_secret, self.redirect_uri, self.issuer = client_id, client_secret, redirect_uri, issuer
        self.key = Key("k1")
        self.extra_keys: list[Key] = []
        self.identity = {"sub": "sub-boss", "email": "boss@kantor.id", "email_verified": True, "name": "Boss"}
        self.claim_overrides: dict = {}
        self.token_status = 200  # set to 400 to make the token endpoint refuse
        self.codes: dict[str, dict] = {}
        self.app = self._build()

    # ---- minting ----------------------------------------------------------
    def mint(self, _nonce: str, /, *, key: Key | None = None, alg="RS256", **claims) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": self.client_id, "iat": now, "exp": now + 600, "nonce": _nonce, **self.identity,
                **self.claim_overrides, **claims}
        body = {k: v for k, v in body.items() if v is not None}  # None removes a claim
        k = key or self.key
        if alg == "none":
            return jwt.encode(body, None, algorithm="none", headers={"kid": k.kid})
        if alg == "HS256":
            return jwt.encode(body, "shared-secret-" * 4, algorithm="HS256", headers={"kid": k.kid})
        return jwt.encode(body, k.pem, algorithm="RS256", headers={"kid": k.kid})

    # ---- the three endpoints Rekamind talks to -----------------------------------
    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.get("/.well-known/openid-configuration")
        async def discovery():
            return {"issuer": self.issuer, "authorization_endpoint": f"{self.issuer}/authorize", "token_endpoint": f"{self.issuer}/token",
                    "jwks_uri": f"{self.issuer}/jwks"}

        @app.get("/jwks")
        async def jwks():
            return {"keys": [self.key.jwk(), *[k.jwk() for k in self.extra_keys]]}

        @app.get("/authorize")
        async def authorize(request: Request):
            q = request.query_params
            assert q["client_id"] == self.client_id and q["redirect_uri"] == self.redirect_uri
            assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
            code = secrets.token_urlsafe(24)
            self.codes[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "used": False}
            return RedirectResponse(f"{self.redirect_uri}?{urlencode({'code': code, 'state': q['state']})}", status_code=302)

        @app.post("/token")
        async def token(grant_type: str = Form(), code: str = Form(), redirect_uri: str = Form(), client_id: str = Form(),
                        client_secret: str = Form(), code_verifier: str = Form()):
            c = self.codes.get(code)
            ok = (self.token_status == 200 and c and not c["used"] and grant_type == "authorization_code"
                  and client_id == self.client_id and client_secret == self.client_secret and redirect_uri == self.redirect_uri
                  and base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode() == c["challenge"])
            if not ok:
                return JSONResponse({"error": "invalid_grant", "error_description": "secret detail that must never reach users"}, status_code=400)
            c["used"] = True
            return {"id_token": self.mint(c["nonce"]), "access_token": "google-access-token-never-stored", "token_type": "Bearer"}

        @app.post("/__identity")  # test control only: which Google account "is signed in" at the provider
        async def set_identity(request: Request):
            self.identity = {"email_verified": True, **await request.json()}
            return {"ok": True}

        return app

    def as_json(self) -> str:
        return json.dumps(self.identity)
