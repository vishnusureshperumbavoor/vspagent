"""
WhatsApp Chat Export Dataset Parser & Sanitizer
===============================================
Parses raw WhatsApp .txt chat exports into clean, multi-turn dialogue
datasets formatted in ChatML for fine-tuning LLMs and personal persona agents.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union

# Match WhatsApp message header lines across Android, iOS, 12h, 24h, non-breaking spaces
HEADER_RE = re.compile(
    r"^\[?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)[\s\u202f\xa0]*([a-zA-Z]{2})?\]?\s*[-–:]?\s*([^:]+):\s*(.*)$"
)

SYSTEM_IGNORE_RE = re.compile(
    r"(Messages and calls are end-to-end encrypted|<Media omitted>|image omitted|audio omitted|video omitted|sticker omitted|document omitted|This message was deleted|You deleted this message|Missed (?:voice|video) call|security code changed|created group|added you|left the group)",
    re.IGNORECASE,
)

PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}|\b\d{10}\b")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def mask_pii(text: str) -> str:
    """Masks phone numbers and email addresses to protect privacy."""
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = PHONE_RE.sub("[PHONE]", text)
    return text


def parse_chat_file(
    file_path: Union[str, Path],
    assistant_names: List[str],
    mask_private_info: bool = True,
) -> List[Dict[str, str]]:
    """Extract individual user/assistant turns from a single WhatsApp export file."""
    path = Path(file_path)
    if not path.is_file():
        return []

    assistant_set = {n.strip().lower() for n in assistant_names}
    turns = []
    current_role = None
    current_text = []

    def commit_turn():
        if current_role and current_text:
            cleaned = "\n".join(current_text).strip()
            if cleaned and not SYSTEM_IGNORE_RE.search(cleaned):
                if mask_private_info:
                    cleaned = mask_pii(cleaned)
                turns.append({"role": current_role, "content": cleaned})

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.rstrip("\r\n")
                m = HEADER_RE.match(line)
                if m:
                    _date, _time, _ampm, sender, content = m.groups()
                    sender_clean = sender.strip().lower()
                    role = "assistant" if any(a in sender_clean for a in assistant_set) else "user"

                    commit_turn()
                    current_role = role
                    current_text = [content.strip()] if content.strip() else []
                else:
                    if current_role is not None:
                        current_text.append(line)

            commit_turn()
    except Exception as e:
        print(f"Warning: Failed reading {path.name}: {e}")

    return turns


def group_turns_into_dialogues(
    turns: List[Dict[str, str]],
    max_turns_per_dialogue: int = 12,
) -> List[Dict[str, List[Dict[str, str]]]]:
    """Group sequential turns into structured ChatML dialogue samples."""
    # Collapse consecutive turns by the same role
    merged_turns = []
    for turn in turns:
        if merged_turns and merged_turns[-1]["role"] == turn["role"]:
            merged_turns[-1]["content"] += "\n" + turn["content"]
        else:
            merged_turns.append(turn.copy())

    dialogues = []
    for idx, turn in enumerate(merged_turns):
        if turn["role"] == "assistant":
            start_idx = max(0, idx - (max_turns_per_dialogue - 1))
            while start_idx < idx and merged_turns[start_idx]["role"] != "user":
                start_idx += 1
            if start_idx < idx:
                sample = merged_turns[start_idx : idx + 1]
                dialogues.append({"messages": sample})

    return dialogues


def parse_whatsapp_chats(
    input_path: Union[str, Path],
    assistant_names: Union[str, List[str]],
    output_path: Optional[Union[str, Path]] = None,
    mask_private_info: bool = True,
    max_turns: int = 24,
) -> List[Dict]:
    """
    Parses a single WhatsApp .txt file or a directory of .txt files into
    ChatML JSONL formatted conversations.
    """
    if isinstance(assistant_names, str):
        assistant_names = [a.strip() for a in assistant_names.split(",")]

    in_path = Path(input_path)
    all_files = []
    if in_path.is_file():
        all_files.append(in_path)
    elif in_path.is_dir():
        all_files.extend(sorted(list(in_path.rglob("*.txt"))))
    else:
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    all_dialogues = []
    for f in all_files:
        turns = parse_chat_file(f, assistant_names=assistant_names, mask_private_info=mask_private_info)
        dialogues = group_turns_into_dialogues(turns, max_turns_per_dialogue=max_turns)
        all_dialogues.extend(dialogues)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            for d in all_dialogues:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

    return all_dialogues
