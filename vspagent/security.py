"""Secret redaction and private-file helpers.

Every log line, tool result, provider error and session entry passes through
``redact`` before it is printed or persisted.  The agent handles API keys, so
redaction is a default, not an opt-in.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

TOKEN_ENV_VARS = (
    "VSPAGENT_API_KEY",
    "KIMI_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "XAI_API_KEY",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
)

TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxai-[A-Za-z0-9]{16,}"),
    re.compile(
        r"(?i)\b(VSPAGENT_API_KEY|KIMI_API_KEY|OPENAI_API_KEY|DEEPSEEK_API_KEY|"
        r"DASHSCOPE_API_KEY|XAI_API_KEY|GEMINI_API_KEY|ANTHROPIC_API_KEY|"
        r"HF_TOKEN)\b\s*[=:]\s*\S+"
    ),
    re.compile(r"(?i)\b(authorization:\s*bearer)\s+\S+"),
    re.compile(r"(?i)\b(x-api-key:\s*)\S+"),
)

MAX_TOOL_OUTPUT = 20_000


def redact(text: str) -> str:
    """Replace token-shaped strings with a marker."""
    if not text:
        return text
    redacted = text
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")


def sanitize_terminal(text: str) -> str:
    """Strip ANSI escapes and control characters from untrusted model output."""
    cleaned = OSC_RE.sub("", ANSI_RE.sub("", text))
    return "".join(
        character
        for character in cleaned
        if character in "\n\t" or (ord(character) >= 32 and character != "\x7f")
    )


def mask_secret(secret: str) -> str:
    """Return a safe fingerprint for display: ``sk-…abcd``."""
    value = (secret or "").strip()
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}…{value[-4:]}"


def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    """Bound tool output so one command cannot flood the context window."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… truncated {len(text) - limit} characters"


def write_private_file(path: str | Path, content: str, mode: int = 0o600) -> Path:
    """Create a file with restrictive permissions before writing its bytes."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        try:
            os.chmod(target, mode)
        except OSError:  # Windows has no POSIX mode bits
            pass
    return target


def is_within(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` resolves inside ``root`` (symlinks included)."""
    try:
        root_resolved = root.resolve(strict=True)
    except OSError:
        root_resolved = root.resolve(strict=False)
    try:
        candidate_resolved = candidate.resolve(strict=False)
    except OSError:
        return False
    return candidate_resolved == root_resolved or root_resolved in candidate_resolved.parents
