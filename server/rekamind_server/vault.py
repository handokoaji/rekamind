"""Encryption at rest for third-party tokens (GitHub, GitLab, webhook signing secrets).

A leaked database dump must not hand out access to someone's repositories. Fernet (AES-128-CBC + HMAC) with a
key from REKAMIND_SECRET_KEY. Single-user modes (desktop, local) need no setup: a random key is created once
in the data folder. A shared server must set the key itself: guessing is not a policy.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import Settings

MIN_KEY_CHARS = 32


class VaultUnavailable(RuntimeError):
    """No usable key: integrations are switched off (with the reason) instead of storing tokens in clear text."""


class Vault:
    def __init__(self, key_material: str):
        if len(key_material) < MIN_KEY_CHARS:
            raise VaultUnavailable(f"REKAMIND_SECRET_KEY harus minimal {MIN_KEY_CHARS} karakter acak")
        material = key_material.encode()
        # The key is random (os.urandom, or a generated REKAMIND_SECRET_KEY), never a human password, so a fast
        # extract-and-expand KDF is the right tool; a slow password hash would add nothing. New tokens use HKDF.
        current = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"rekamind-vault-v2").derive(material)
        # Tokens sealed before v2 used a plain SHA-256 of the key. Keep them readable (decrypt-only: MultiFernet
        # always seals with the first key), otherwise every saved GitHub/GitLab/webhook secret would be lost.
        legacy = hashlib.sha256(material).digest()
        self._f = MultiFernet([Fernet(base64.urlsafe_b64encode(current)), Fernet(base64.urlsafe_b64encode(legacy))])

    def seal(self, plain: str) -> str:
        return self._f.encrypt(plain.encode()).decode()

    def open(self, token: str) -> str:
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise VaultUnavailable("Kunci enkripsi berubah: token tersimpan tidak bisa dibuka. Simpan ulang token integrasinya.") from exc


def load_vault(settings: Settings) -> Vault | VaultUnavailable:
    """A Vault, or the reason there is none (returned, not raised, so startup never fails because of it)."""
    if settings.secret_key:
        try:
            return Vault(settings.secret_key)
        except VaultUnavailable as exc:
            return exc
    if settings.auth in ("local_token", "none"):
        path = Path(settings.data_dir) / "secret.key"
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                key = base64.urlsafe_b64encode(os.urandom(48)).decode()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(key)
            with contextlib.suppress(OSError):
                path.chmod(0o600)
            return Vault(path.read_text().strip())
        except OSError as exc:
            return VaultUnavailable(f"Tidak bisa membuat kunci enkripsi lokal: {exc}")
    return VaultUnavailable("Integrasi butuh REKAMIND_SECRET_KEY (minimal 32 karakter acak) di server bersama. "
                            "Buat dengan: python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
