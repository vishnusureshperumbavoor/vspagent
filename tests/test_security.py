"""Secret redaction and workspace containment."""

from __future__ import annotations

import os
import stat

from vspagent.security import (
    is_within,
    mask_secret,
    redact,
    sanitize_terminal,
    truncate,
    write_private_file,
)


def test_api_keys_are_redacted() -> None:
    text = "key=sk-abcdefghijklmnopqrstuvwxyz KIMI_API_KEY=supersecret"

    cleaned = redact(text)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in cleaned
    assert "supersecret" not in cleaned
    assert "[REDACTED]" in cleaned


def test_authorization_and_x_api_key_headers_are_redacted() -> None:
    cleaned = redact("Authorization: Bearer abc123\nx-api-key: xyz789")

    assert "abc123" not in cleaned
    assert "xyz789" not in cleaned


def test_normal_text_is_untouched() -> None:
    assert redact("loss=0.42 step=10") == "loss=0.42 step=10"


def test_terminal_control_sequences_are_stripped() -> None:
    cleaned = sanitize_terminal("safe\x1b[31mred\x07\nnext")

    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "safered" in cleaned
    assert "\nnext" in cleaned


def test_mask_secret_shows_only_a_fingerprint() -> None:
    assert mask_secret("sk-1234567890abcdef") == "sk-…cdef"
    assert mask_secret("short") == "***"


def test_truncate_bounds_output() -> None:
    result = truncate("x" * 50, limit=10)

    assert result.startswith("x" * 10)
    assert "truncated" in result


def test_write_private_file_uses_mode_600(tmp_path) -> None:
    target = write_private_file(tmp_path / "auth.json", "{}")

    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_is_within_accepts_children_and_rejects_escapes(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "src" / "app.py"

    assert is_within(root, inside)
    assert not is_within(root, tmp_path / "outside.txt")


def test_is_within_resolves_symlinks(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        return

    assert not is_within(root, link)
