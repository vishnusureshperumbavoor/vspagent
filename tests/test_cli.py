"""CLI wiring, auth commands and configuration commands."""

from __future__ import annotations

import io

import pytest

from vspagent.cli import main
from vspagent.config import load_config


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("VSPAGENT_AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setenv("VSPAGENT_DISABLE_KEYRING", "1")
    monkeypatch.setenv("VSPAGENT_DATA_DIR", str(tmp_path / "data"))
    for name in ("KIMI_API_KEY", "VSPAGENT_API_KEY", "VSPAGENT_PROVIDER", "VSPAGENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_version_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert "vspagent 4.0.0" in capsys.readouterr().out


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    assert "Terminal coding agent" in capsys.readouterr().out


def test_auth_status_does_not_need_a_key(isolated, capsys) -> None:
    assert main(["auth", "status"]) == 0
    assert "kimi" in capsys.readouterr().out


def test_auth_login_from_stdin_stores_a_key(isolated, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-key-123456789\n"))

    assert main(["auth", "login", "kimi", "--stdin"]) == 0
    output = capsys.readouterr().out
    assert "Stored kimi key" in output
    assert "stdin-key-123456789" not in output


def test_auth_logout(isolated, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-key-123456789\n"))
    main(["auth", "login", "kimi", "--stdin"])

    assert main(["auth", "logout", "kimi"]) == 0


def test_config_shows_defaults(isolated, capsys) -> None:
    assert main(["config"]) == 0
    output = capsys.readouterr().out
    assert "https://api.moonshot.ai/v1" in output


def test_config_init_writes_a_file(isolated, capsys) -> None:
    assert main(["config", "--init"]) == 0
    path = isolated / "config.toml"

    assert path.exists()
    assert "[providers.kimi]" in path.read_text(encoding="utf-8")
    assert "Wrote" in capsys.readouterr().out


def test_sessions_list_is_empty_at_first(isolated, capsys) -> None:
    assert main(["sessions", "list"]) == 0
    assert "No sessions yet" in capsys.readouterr().out


def test_models_without_a_key_is_a_readable_error(isolated, capsys) -> None:
    assert main(["models"]) == 1
    assert "no API key" in capsys.readouterr().err


def test_unknown_provider_is_a_readable_error(isolated, capsys) -> None:
    assert main(["--provider", "banana", "hello"]) == 1
    assert "unknown provider" in capsys.readouterr().err


def test_default_provider_is_kimi(isolated) -> None:
    config = load_config()

    assert config.provider == "kimi"
    assert config.provider_config().model == "kimi-k2.7-code"
