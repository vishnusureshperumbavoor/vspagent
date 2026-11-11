"""API-key resolution and storage."""

from __future__ import annotations

import io
import os
import stat

import pytest

from vspagent import auth


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VSPAGENT_AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setenv("VSPAGENT_DISABLE_KEYRING", "1")
    for name in ("KIMI_API_KEY", "VSPAGENT_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "auth.json"


def test_environment_wins(auth_env, monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "env-key-123456789")

    assert auth.get_key("kimi", "KIMI_API_KEY") == "env-key-123456789"
    assert auth.key_source("kimi", "KIMI_API_KEY") == "environment"


def test_store_and_read_from_private_file(auth_env) -> None:
    backend = auth.store_key("kimi", "file-key-123456789")

    assert backend == "file"
    assert auth.get_key("kimi", "KIMI_API_KEY") == "file-key-123456789"
    assert auth.key_source("kimi", "KIMI_API_KEY") == "file"
    assert stat.S_IMODE(os.stat(auth_env).st_mode) == 0o600


def test_delete_key(auth_env) -> None:
    auth.store_key("kimi", "file-key-123456789")

    assert auth.delete_key("kimi") is True
    assert auth.get_key("kimi", "KIMI_API_KEY") == ""
    assert auth.delete_key("kimi") is False


def test_login_from_stdin(auth_env, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-key-123456789\n"))

    provider, backend = auth.login("kimi", from_stdin=True)

    assert provider == "kimi"
    assert backend == "file"
    assert auth.get_key("kimi", "KIMI_API_KEY") == "stdin-key-123456789"


def test_login_with_explicit_key(auth_env) -> None:
    provider, backend = auth.login("kimi", key="explicit-key-123456789")

    assert (provider, backend) == ("kimi", "file")


@pytest.mark.parametrize("key", ["", "short", "has space in key"])
def test_bad_keys_are_rejected(auth_env, key: str) -> None:
    with pytest.raises(auth.AuthError):
        auth.store_key("kimi", key)


def test_status_masks_keys(auth_env) -> None:
    auth.store_key("kimi", "file-key-123456789")

    rows = auth.status({"kimi": "KIMI_API_KEY"})

    assert rows[0]["provider"] == "kimi"
    assert rows[0]["source"] == "file"
    assert "123456789" not in rows[0]["key"]
    assert rows[0]["key"].endswith("6789")
