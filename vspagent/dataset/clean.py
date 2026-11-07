"""
Persona Dataset Cleaner, Deduplicator & Sanitizer
=================================================
Turns raw ChatML JSONL (e.g. WhatsApp exports or mixed synthetic data) into a
compact, non-repetitive training set. The goal is to stop small models from
mode-collapsing into a handful of memorized FAQ answers.

The cleaner drops whole dialogue samples, never individual turns, so every
remaining sample stays a valid ChatML conversation ending on an assistant turn.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:
    from .whatsapp import mask_pii
except ImportError:  # pragma: no cover - direct module execution
    from whatsapp import mask_pii

DEFAULT_MAX_CHARS = 700
DEFAULT_MIN_2TURN_ANSWER = 8
DEFAULT_MAX_URL_LEN = 100
DEFAULT_MAX_TURNS = 8

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
CODE_RE = re.compile(r"```|^\s*(?:import|from|def|class|function|const|let|var)\s", re.MULTILINE)

# Conservative adult/spam domains found in noisy chat exports.
DEFAULT_DROP_PATTERNS: Tuple[str, ...] = (
    r"xnxx",
    r"pornhub",
    r"xvideos",
    r"onlyfans",
)

VALID_ROLES = {"user", "assistant"}


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_messages(
    messages: Sequence[Dict[str, Any]],
    strip_system: bool = True,
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip().lower()
        content = message.get("content")
        if role not in VALID_ROLES:
            if role == "system" and strip_system:
                continue
            if role != "system":
                continue
        if not isinstance(content, str):
            continue
        content = _normalize_text(content)
        if not content:
            continue
        if normalized and normalized[-1]["role"] == role:
            normalized[-1]["content"] = f"{normalized[-1]['content']}\n{content}"
        else:
            normalized.append({"role": role, "content": content})
    return normalized


def _assistant_key(messages: Sequence[Dict[str, str]]) -> Tuple[str, ...]:
    return tuple(m["content"] for m in messages if m["role"] == "assistant")


def _sample_key(messages: Sequence[Dict[str, str]]) -> Tuple[Tuple[str, str], ...]:
    return tuple((m["role"], m["content"]) for m in messages)


def clean_samples(
    samples: Iterable[Dict[str, Any]],
    max_chars: int = DEFAULT_MAX_CHARS,
    min_2turn_answer: int = DEFAULT_MIN_2TURN_ANSWER,
    max_url_len: int = DEFAULT_MAX_URL_LEN,
    max_turns: int = DEFAULT_MAX_TURNS,
    drop_code: bool = True,
    drop_patterns: Optional[Sequence[str]] = None,
    dedupe_by: str = "answer",
    max_answer_variants: int = 3,
    mask_private_info: bool = False,
    strip_system: bool = True,
) -> Tuple[List[Dict[str, List[Dict[str, str]]]], Dict[str, Any]]:
    """Filter and deduplicate ChatML samples, returning cleaned data + a report."""
    patterns = [re.compile(p, re.IGNORECASE) for p in (drop_patterns or DEFAULT_DROP_PATTERNS)]
    cleaned: List[Dict[str, List[Dict[str, str]]]] = []
    seen_exact = set()
    answer_counts: Dict[Tuple[str, ...], int] = {}

    report: Dict[str, Any] = {
        "input_samples": 0,
        "output_samples": 0,
        "invalid": 0,
        "too_many_turns": 0,
        "code": 0,
        "too_long": 0,
        "long_url": 0,
        "blocked_pattern": 0,
        "short_2turn": 0,
        "duplicate_exact": 0,
        "duplicate_answer": 0,
        "avg_turns_before": 0.0,
        "avg_turns_after": 0.0,
    }
    turns_before = 0
    turns_after = 0

    for sample in samples:
        report["input_samples"] += 1
        messages = sample.get("messages") if isinstance(sample, dict) else None
        if not isinstance(messages, list):
            report["invalid"] += 1
            continue
        turns_before += len(messages)

        messages = _normalize_messages(messages, strip_system=strip_system)
        if (
            len(messages) < 2
            or messages[-1]["role"] != "assistant"
            or not any(m["role"] == "user" for m in messages)
        ):
            report["invalid"] += 1
            continue

        if len(messages) > max_turns:
            report["too_many_turns"] += 1
            continue

        if max_chars and any(len(m["content"]) > max_chars for m in messages):
            report["too_long"] += 1
            continue

        if drop_code and any(CODE_RE.search(m["content"]) for m in messages):
            report["code"] += 1
            continue

        if max_url_len and any(
            len(url) > max_url_len for m in messages for url in URL_RE.findall(m["content"])
        ):
            report["long_url"] += 1
            continue

        if any(p.search(m["content"]) for p in patterns for m in messages):
            report["blocked_pattern"] += 1
            continue

        if (
            len(messages) == 2
            and min_2turn_answer
            and len(messages[1]["content"]) < min_2turn_answer
        ):
            report["short_2turn"] += 1
            continue

        if mask_private_info:
            for m in messages:
                m["content"] = mask_pii(m["content"])

        exact_key = _sample_key(messages)
        if dedupe_by != "none" and exact_key in seen_exact:
            report["duplicate_exact"] += 1
            continue

        if dedupe_by == "answer":
            answer_key = _assistant_key(messages)
            count = answer_counts.get(answer_key, 0)
            if count >= max_answer_variants:
                report["duplicate_answer"] += 1
                continue
            answer_counts[answer_key] = count + 1

        seen_exact.add(exact_key)
        cleaned.append({"messages": messages})
        turns_after += len(messages)

    report["output_samples"] = len(cleaned)
    report["avg_turns_before"] = round(turns_before / report["input_samples"], 2) if report["input_samples"] else 0.0
    report["avg_turns_after"] = round(turns_after / len(cleaned), 2) if cleaned else 0.0
    report["unique_assistant_messages"] = len(answer_counts) if dedupe_by == "answer" else None
    return cleaned, report


def clean_jsonl(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    shuffle: bool = False,
    seed: int = 42,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Clean a ChatML JSONL file and optionally write the result."""
    in_path = Path(input_path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Input dataset not found: {input_path}")

    samples = []
    parse_errors = 0
    with open(in_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                parse_errors += 1

    cleaned, report = clean_samples(samples, **kwargs)
    report["parse_errors"] = parse_errors

    if shuffle:
        random.Random(seed).shuffle(cleaned)

    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as handle:
            for sample in cleaned:
                handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
        report["output_path"] = str(out_path)

    return report
