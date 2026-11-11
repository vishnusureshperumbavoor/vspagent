"""API-key storage: environment, OS keyring, then a mode-600 fallback file."""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

from vspagent.security import mask_secret, write_private_file

KEYRING_SERVICE = "vspagent"


class AuthError(RuntimeError):
    """Raised when a key is missing or cannot be stored."""


def _keyring():
    """Return the keyring module, or ``None`` when unavailable/disabled."""
    if os.getenv("VSPAGENT_DISABLE_KEYRING"):
        return None
    try:
        import keyring

        backend = keyring.get_keyring()
        name = backend.__class__.__name__.lower()
        if "fail" in name or "null" in name:
            return None
        return keyring
    except Exception:  # noqa: BLE001 - keyring backends vary wildly
        return None


def _auth_file() -> Path:
    from vspagent.config import auth_path

    return auth_path()


def _read_file() -> dict[str, str]:
    path = _auth_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if isinstance(value, str)}


def _write_file(data: dict[str, str]) -> None:
    write_private_file(_auth_file(), json.dumps(data, indent=2), mode=0o600)


def env_key(provider_name: str, api_key_env: str = "") -> str:
    """Return a key from the environment, if one is set."""
    for name in (api_key_env, "VSPAGENT_API_KEY"):
        if not name:
            continue
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def get_key(provider_name: str, api_key_env: str = "") -> str:
    """Resolve a key: environment, keyring, then fallback file."""
    value = env_key(provider_name, api_key_env)
    if value:
        return value
    ring = _keyring()
    if ring is not None:
        try:
            stored = ring.get_password(KEYRING_SERVICE, provider_name)
            if stored:
                return stored
        except Exception:  # noqa: BLE001 - backend may be locked
            pass
    return _read_file().get(provider_name, "")


def key_source(provider_name: str, api_key_env: str = "") -> str:
    if env_key(provider_name, api_key_env):
        return "environment"
    ring = _keyring()
    if ring is not None:
        try:
            if ring.get_password(KEYRING_SERVICE, provider_name):
                return "keyring"
        except Exception:  # noqa: BLE001
            pass
    if _read_file().get(provider_name):
        return "file"
    return "missing"


def store_key(provider_name: str, key: str) -> str:
    """Store a key in the keyring, falling back to the private file."""
    value = (key or "").strip()
    if not value or any(character.isspace() for character in value):
        raise AuthError("API key is empty or contains whitespace")
    if len(value) < 8:
        raise AuthError("API key looks too short")
    ring = _keyring()
    if ring is not None:
        try:
            ring.set_password(KEYRING_SERVICE, provider_name, value)
            return "keyring"
        except Exception:  # noqa: BLE001 - fall back to the file
            pass
    data = _read_file()
    data[provider_name] = value
    _write_file(data)
    return "file"


def delete_key(provider_name: str) -> bool:
    removed = False
    ring = _keyring()
    if ring is not None:
        try:
            ring.delete_password(KEYRING_SERVICE, provider_name)
            removed = True
        except Exception:  # noqa: BLE001 - not stored there
            pass
    data = _read_file()
    if provider_name in data:
        data.pop(provider_name)
        _write_file(data)
        removed = True
    return removed


def login(provider_name: str, key: str | None = None, from_stdin: bool = False) -> tuple[str, str]:
    """Store a key and return ``(provider, storage_backend)``."""
    value = key
    if not value and from_stdin:
        value = sys.stdin.readline().strip()
    if not value:
        value = getpass.getpass(f"{provider_name} API key: ")
    backend = store_key(provider_name, value)
    return provider_name, backend


def status(providers: dict[str, str]) -> list[dict[str, str]]:
    """Describe configured keys without revealing them."""
    rows = []
    for name, api_key_env in sorted(providers.items()):
        source = key_source(name, api_key_env)
        value = get_key(name, api_key_env)
        rows.append(
            {
                "provider": name,
                "source": source,
                "key": mask_secret(value) if value else "—",
            }
        )
    return rows
