import json
from unittest.mock import MagicMock

from app import update_check


def _fake_urlopen(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=response)


def test_returns_none_when_url_is_blank():
    assert update_check.check_for_update("0.1.0", "") is None


def test_detects_newer_version_github_shape(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.2.0"}))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") == "0.2.0"


def test_detects_newer_version_gitlab_shape(monkeypatch):
    """GitLab's releases endpoint returns a list, newest first."""
    monkeypatch.setattr(
        update_check.urllib.request, "urlopen",
        _fake_urlopen([{"tag_name": "v0.3.0"}, {"tag_name": "v0.2.0"}]),
    )
    assert update_check.check_for_update("0.1.0", "https://gitlab.example/releases") == "0.3.0"


def test_returns_none_when_already_latest(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.1.0"}))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None


def test_returns_none_when_current_is_newer_than_remote(monkeypatch):
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _fake_urlopen({"tag_name": "v0.1.0"}))
    assert update_check.check_for_update("0.2.0", "https://api.example/releases/latest") is None


def test_returns_none_on_network_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError("network unreachable")
    monkeypatch.setattr(update_check.urllib.request, "urlopen", _raise)
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None


def test_returns_none_on_malformed_response(monkeypatch):
    response = MagicMock()
    response.read.return_value = b"not json"
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(update_check.urllib.request, "urlopen", MagicMock(return_value=response))
    assert update_check.check_for_update("0.1.0", "https://api.example/releases/latest") is None
