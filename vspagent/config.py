"""Configuration, provider defaults and XDG paths."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "vspagent"
DEFAULT_PROVIDER = "kimi"
DEFAULT_PERMISSION_MODE = "ask"
DEFAULT_MAX_ITERATIONS = 30
DEFAULT_TIMEOUT = 120.0

PERMISSION_MODES = ("ask", "allowlist", "yolo")


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


@dataclass
class ProviderConfig:
    """One OpenAI-compatible endpoint."""

    name: str
    type: str = "openai_compatible"
    base_url: str = ""
    api_key_env: str = ""
    model: str = ""
    auth_style: str = "bearer"
    extra_headers: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.type != "openai_compatible":
            raise ConfigError(
                f"provider {self.name!r} has unsupported type {self.type!r}; "
                "only 'openai_compatible' is available in v4"
            )
        if not self.base_url.startswith(("https://", "http://")):
            raise ConfigError(
                f"provider {self.name!r} needs an http(s) base_url, got {self.base_url!r}"
            )
        if not self.model:
            raise ConfigError(f"provider {self.name!r} has no model configured")
        if self.auth_style not in {"bearer", "x-api-key", "none"}:
            raise ConfigError(
                f"provider {self.name!r} has unsupported auth_style {self.auth_style!r}"
            )


_PROVIDER_SPECS: dict[str, tuple[str, str, str]] = {
    "kimi": ("https://api.moonshot.ai/v1", "KIMI_API_KEY", "kimi-k2.7-code"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-codex"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-coder"),
    "qwen": (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY",
        "qwen3-coder-plus",
    ),
    "grok": ("https://api.x.ai/v1", "XAI_API_KEY", "grok-code-fast-1"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini-2.5-pro",
    ),
}

DEFAULT_PROVIDERS: dict[str, ProviderConfig] = {
    name: ProviderConfig(name=name, base_url=base_url, api_key_env=api_key_env, model=model)
    for name, (base_url, api_key_env, model) in _PROVIDER_SPECS.items()
}


@dataclass
class Config:
    provider: str = DEFAULT_PROVIDER
    model: str = ""
    permission_mode: str = DEFAULT_PERMISSION_MODE
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    timeout: float = DEFAULT_TIMEOUT
    path: Path | None = None
    providers: dict[str, ProviderConfig] = field(
        default_factory=lambda: {name: ProviderConfig(**vars(cfg)) for name, cfg in DEFAULT_PROVIDERS.items()}
    )

    def provider_config(self, name: str | None = None) -> ProviderConfig:
        selected = (name or self.provider or DEFAULT_PROVIDER).strip().lower()
        if selected not in self.providers:
            known = ", ".join(sorted(self.providers))
            raise ConfigError(f"unknown provider {selected!r}; known providers: {known}")
        provider = ProviderConfig(**vars(self.providers[selected]))
        if self.model and selected == self.provider:
            provider.model = self.model
        provider.validate()
        return provider

    def provider_names(self) -> list[str]:
        return sorted(self.providers)


def config_dir() -> Path:
    override = os.getenv("VSPAGENT_CONFIG_DIR")
    return Path(override).expanduser() if override else Path(user_config_dir(APP_NAME))


def data_dir() -> Path:
    override = os.getenv("VSPAGENT_DATA_DIR")
    return Path(override).expanduser() if override else Path(user_data_dir(APP_NAME))


def config_path() -> Path:
    override = os.getenv("VSPAGENT_CONFIG")
    return Path(override).expanduser() if override else config_dir() / "config.toml"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def history_path() -> Path:
    return data_dir() / "history"


def auth_path() -> Path:
    return Path(os.getenv("VSPAGENT_AUTH_FILE", config_dir() / "auth.json")).expanduser()


def _merge_provider(name: str, raw: Any, fallback: ProviderConfig) -> ProviderConfig:
    if not isinstance(raw, dict):
        return fallback
    merged = {**vars(fallback), **{key: value for key, value in raw.items() if key in vars(fallback)}}
    merged["name"] = name
    return ProviderConfig(**merged)


def _from_mapping(data: dict[str, Any], path: Path | None = None) -> Config:
    general = data.get("general", {}) if isinstance(data.get("general"), dict) else {}
    config = Config(path=path, providers={})
    config.provider = str(general.get("provider", DEFAULT_PROVIDER)).strip().lower()
    config.model = str(general.get("model", "") or "")
    config.permission_mode = str(general.get("permission_mode", DEFAULT_PERMISSION_MODE))
    config.max_iterations = int(general.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    config.timeout = float(general.get("timeout", DEFAULT_TIMEOUT))

    for name, provider in DEFAULT_PROVIDERS.items():
        config.providers[name] = ProviderConfig(**vars(provider))
    raw_providers = data.get("providers", {})
    if isinstance(raw_providers, dict):
        for name, raw in raw_providers.items():
            fallback = config.providers.get(name, ProviderConfig(name=str(name)))
            config.providers[str(name)] = _merge_provider(str(name), raw, fallback)
    return config


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml, falling back to built-in provider defaults."""
    target = Path(path).expanduser() if path else config_path()
    data: dict[str, Any] = {}
    if target.exists():
        try:
            data = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read {target}: {exc}") from exc
    config = _from_mapping(data, path=target)

    env_provider = os.getenv("VSPAGENT_PROVIDER")
    if env_provider:
        config.provider = env_provider.strip().lower()
    env_model = os.getenv("VSPAGENT_MODEL")
    if env_model:
        config.model = env_model.strip()
    env_mode = os.getenv("VSPAGENT_PERMISSION_MODE")
    if env_mode:
        config.permission_mode = env_mode.strip().lower()
    env_base = os.getenv("VSPAGENT_BASE_URL")
    if env_base:
        selected = config.provider
        if selected not in config.providers:
            config.providers[selected] = ProviderConfig(name=selected)
        config.providers[selected].base_url = env_base.strip()

    if config.permission_mode not in PERMISSION_MODES:
        raise ConfigError(
            f"permission_mode must be one of {', '.join(PERMISSION_MODES)}; "
            f"got {config.permission_mode!r}"
        )
    if config.max_iterations < 1:
        raise ConfigError("max_iterations must be at least 1")
    return config


def render_default_config(config: Config) -> str:
    """Render a documented TOML config without importing tomli-w."""
    lines = [
        "# vspagent configuration",
        "",
        "[general]",
        f'provider = "{config.provider}"',
        f'permission_mode = "{config.permission_mode}"',
        f"max_iterations = {config.max_iterations}",
        f"timeout = {config.timeout}",
        "",
    ]
    for name, provider in config.providers.items():
        lines += [
            f"[providers.{name}]",
            f'type = "{provider.type}"',
            f'base_url = "{provider.base_url}"',
            f'api_key_env = "{provider.api_key_env}"',
            f'model = "{provider.model}"',
            f'auth_style = "{provider.auth_style}"',
            "",
        ]
    return "\n".join(lines)


def write_default_config(path: str | Path | None = None, force: bool = False) -> Path:
    """Write a starter config; never overwrite unless ``force`` is set."""
    from vspagent.security import write_private_file

    target = Path(path).expanduser() if path else config_path()
    if target.exists() and not force:
        raise ConfigError(f"{target} already exists; pass --force to overwrite")
    config = load_config()
    target.parent.mkdir(parents=True, exist_ok=True)
    return write_private_file(target, render_default_config(config), mode=0o600)
