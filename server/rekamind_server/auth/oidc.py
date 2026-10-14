"""Talking to Google (OpenID Connect) and, above all, deciding whether an ID token can be trusted.

Everything a login grants depends on `verify_id_token`, so it is deliberately strict: one
algorithm (RS256), a signature checked against the issuer's published keys, and every claim that
binds the token to *this* login attempt and *this* server is required, not optional.
"""

import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
_DISCOVERY_TTL = 3600
_JWKS_MIN_REFRESH = 300  # an unknown key id may trigger a refetch, but not more often than this


class InvalidToken(Exception):
    """Carries a reason for logs; callers show users a generic message, never this text."""


class OidcError(Exception):
    """The provider could not be reached or answered nonsense."""


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str
    name: str | None
    picture: str | None


class OidcClient:
    def __init__(self, *, issuer: str, client_id: str, client_secret: str, redirect_uri: str, http: httpx.AsyncClient):
        self.issuer = issuer.rstrip("/")
        self.client_id, self._secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self._http = http
        self._discovery: dict | None = None
        self._discovery_at = 0.0
        self._jwks: dict[str, dict] = {}
        # time.monotonic() counts from boot: 0.0 would read as "just fetched" for the first minutes after a restart
        self._jwks_at = float("-inf")

    # ---- provider metadata --------------------------------------------------
    async def discovery(self) -> dict:
        if self._discovery and time.monotonic() - self._discovery_at < _DISCOVERY_TTL:
            return self._discovery
        try:
            r = await self._http.get(f"{self.issuer}/.well-known/openid-configuration", timeout=10)
            r.raise_for_status()
            doc = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("tidak bisa membaca konfigurasi penyedia login") from exc
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
            if key not in doc:
                raise OidcError(f"konfigurasi penyedia login tidak lengkap ({key})")
        # The document must describe the issuer we asked about, or a hijacked discovery URL could
        # point us at someone else's keys.
        if doc["issuer"].rstrip("/") != self.issuer:
            raise OidcError("penerbit pada konfigurasi tidak cocok")
        self._discovery, self._discovery_at = doc, time.monotonic()
        return doc

    async def _signing_key(self, kid: str | None) -> jwt.PyJWK:
        doc = await self.discovery()
        stale = time.monotonic() - self._jwks_at > _DISCOVERY_TTL
        if kid not in self._jwks and (stale or time.monotonic() - self._jwks_at > _JWKS_MIN_REFRESH):
            try:
                r = await self._http.get(doc["jwks_uri"], timeout=10)
                r.raise_for_status()
                self._jwks = {k["kid"]: k for k in r.json().get("keys", []) if "kid" in k}
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                raise OidcError("tidak bisa mengambil kunci penandatangan") from exc
            self._jwks_at = time.monotonic()
        if kid not in self._jwks:
            raise InvalidToken("unknown signing key")
        return jwt.PyJWK.from_dict(self._jwks[kid])

    # ---- the login round trip ----------------------------------------------
    async def authorization_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        doc = await self.discovery()
        q = {
            "client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": "openid email profile", "state": state, "nonce": nonce,
            "code_challenge": code_challenge, "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{doc['authorization_endpoint']}?{urlencode(q)}"

    async def exchange_code(self, *, code: str, code_verifier: str) -> str:
        """Authorization code -> ID token. The client secret never leaves this server."""
        doc = await self.discovery()
        try:
            r = await self._http.post(
                doc["token_endpoint"], timeout=15,
                data={"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
                      "client_id": self.client_id, "client_secret": self._secret, "code_verifier": code_verifier},
            )
        except httpx.HTTPError as exc:
            raise OidcError("tidak bisa menghubungi penyedia login") from exc
        if r.status_code != 200:
            raise InvalidToken(f"token endpoint refused the code (HTTP {r.status_code})")
        try:
            return r.json()["id_token"]
        except (ValueError, KeyError) as exc:
            raise InvalidToken("token response has no id_token") from exc

    async def verify_id_token(self, id_token: str, *, expected_nonce: str) -> Identity:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise InvalidToken("malformed token") from exc
        if header.get("alg") != "RS256":  # never trust the token's own choice: rules out "none" and HS256 tricks
            raise InvalidToken(f"unexpected algorithm {header.get('alg')!r}")
        key = await self._signing_key(header.get("kid"))
        valid_issuers = GOOGLE_ISSUERS if self.issuer == "https://accounts.google.com" else {self.issuer}
        try:
            claims = jwt.decode(
                id_token, key.key, algorithms=["RS256"], audience=self.client_id, leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iss": False},
            )
        except jwt.PyJWTError as exc:
            raise InvalidToken(f"signature or standard claims rejected: {type(exc).__name__}") from exc
        if claims["iss"] not in valid_issuers:
            raise InvalidToken("wrong issuer")
        aud = claims["aud"]
        if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != self.client_id:
            raise InvalidToken("multiple audiences without matching azp")
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce.encode(), expected_nonce.encode()):
            raise InvalidToken("nonce mismatch (token was not issued for this login)")
        email = claims.get("email")
        if not isinstance(email, str) or not email or claims.get("email_verified") is not True:
            raise InvalidToken("email missing or not verified by the provider")
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise InvalidToken("empty subject")
        return Identity(sub=sub, email=email.strip().lower(), name=claims.get("name"), picture=claims.get("picture"))
