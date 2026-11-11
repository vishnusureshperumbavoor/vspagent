"""The installer must remain shell-valid and use the documented uv flow."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_install_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / "install.sh")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_install_script_uses_uv_and_pins_a_version() -> None:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "uv tool install" in text
    assert "VSPAGENT_VERSION" in text
    assert "sudo" not in text
