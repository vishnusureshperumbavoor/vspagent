"""Configuration loading, provider defaults and overrides."""

from __future__ import annotations

import pytest

from vspagent.config import (
    ConfigError,
    ProviderConfig,
    load_config,
    render_default_config,
    write_default_config,
)


def clear_env(monkeypatch) -> None:
    for name in (
        "VSPAGENT_PROVIDER",
        "VSPAGENT_MODEL",
        "VSPAGENT_PERMISSION_MODE",
        "VSPAGENT_BASE_URL",
        "VSPAGENT_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_use_kimi(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "missing.toml"))

    config = load_config()

    assert config.provider == "kimi"
    provider = config.provider_config()
    assert provider.base_url == "https://api.moonshot.ai/v1"
    assert provider.api_key_env == "KIMI_API_KEY"
    assert provider.model == "kimi-k2.7-code"


def test_env_overrides_provider_and_model(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("VSPAGENT_PROVIDER", "openai")
    monkeypatch.setenv("VSPAGENT_MODEL", "gpt-test")
    monkeypatch.setenv("VSPAGENT_PERMISSION_MODE", "yolo")

    config = load_config()

    assert config.provider == "openai"
    assert config.permission_mode == "yolo"
    assert config.provider_config().model == "gpt-test"


def test_base_url_can_be_overridden_for_local_servers(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("VSPAGENT_BASE_URL", "http://127.0.0.1:11434/v1")

    assert load_config().provider_config().base_url == "http://127.0.0.1:11434/v1"


def test_unknown_provider_is_a_readable_error(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "missing.toml"))

    with pytest.raises(ConfigError, match="unknown provider"):
        load_config().provider_config("banana")


def test_invalid_permission_mode_is_rejected(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    path = tmp_path / "config.toml"
    path.write_text('[general]\npermission_mode = "everything"\n', encoding="utf-8")
    monkeypatch.setenv("VSPAGENT_CONFIG", str(path))

    with pytest.raises(ConfigError, match="permission_mode"):
        load_config()


def test_custom_provider_from_toml(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[general]",
                'provider = "local"',
                "",
                "[providers.local]",
                'type = "openai_compatible"',
                'base_url = "http://127.0.0.1:1234/v1"',
                'api_key_env = "LOCAL_API_KEY"',
                'model = "local-coder"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VSPAGENT_CONFIG", str(path))

    provider = load_config().provider_config()

    assert provider.name == "local"
    assert provider.base_url == "http://127.0.0.1:1234/v1"
    assert provider.model == "local-coder"


def test_provider_validation_rejects_bad_base_url() -> None:
    provider = ProviderConfig(name="x", base_url="ftp://example", model="m")

    with pytest.raises(ConfigError):
        provider.validate()


def test_provider_validation_rejects_unknown_type() -> None:
    provider = ProviderConfig(name="x", type="anthropic", base_url="https://x", model="m")

    with pytest.raises(ConfigError):
        provider.validate()


def test_write_default_config_does_not_overwrite(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    target = tmp_path / "config.toml"

    written = write_default_config(target)
    assert written.exists()
    with pytest.raises(ConfigError, match="already exists"):
        write_default_config(target)
    write_default_config(target, force=True)


def test_rendered_config_lists_providers(tmp_path, monkeypatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("VSPAGENT_CONFIG", str(tmp_path / "missing.toml"))

    rendered = render_default_config(load_config())

    assert "[providers.kimi]" in rendered
    assert "https://api.moonshot.ai/v1" in rendered
