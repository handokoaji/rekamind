import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from rekamind_server.vault import Vault, VaultUnavailable

KEY = "k" * 40


def test_round_trip():
    v = Vault(KEY)
    assert v.open(v.seal("ghp_SECRET")) == "ghp_SECRET"


def test_tokens_sealed_before_hkdf_are_still_readable():
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(KEY.encode()).digest()))
    assert Vault(KEY).open(legacy.encrypt(b"ghp_OLD").decode()) == "ghp_OLD"


def test_new_tokens_are_not_sealed_with_the_legacy_key():
    legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(KEY.encode()).digest()))
    sealed = Vault(KEY).seal("ghp_NEW")
    with pytest.raises(Exception):  # noqa: B017 - InvalidToken
        legacy.decrypt(sealed.encode())


def test_a_different_key_cannot_open_a_token():
    with pytest.raises(VaultUnavailable):
        Vault("z" * 40).open(Vault(KEY).seal("x"))


def test_short_keys_are_refused():
    with pytest.raises(VaultUnavailable):
        Vault("short")
