# 🤖 AGENTS.md — VSP Agent Instruction Manual

Instructions for coding agents working on `vspagent` v4.

`vspagent` is a terminal coding agent. It reads files, edits code, runs commands
with permission, and streams responses from OpenAI-compatible APIs. It is **not**
a GPU harness anymore: Colab/Jarvis live in git history at `v3.3.0-harness`, and
fine-tuning lives in `vsptrainagents`.

---

## 📏 Definition of done

Every change must pass:

```bash
.venv/bin/ruff check .
.venv/bin/python scripts/check_quality.py
.venv/bin/python -m pytest
```

They take seconds and require no API key, network or GPU. If a test needs a real
provider, it is testing at the wrong layer — use `httpx.MockTransport` or a fake
provider.

---

## 🗂️ Where code goes

| You are adding… | Put it in | Never in |
| :--- | :--- | :--- |
| A provider adapter | `vspagent/agent/providers/` | a tool or the UI |
| A tool | `vspagent/agent/tools/` | the agent loop |
| The stream/tool loop | `vspagent/agent/loop.py` | the CLI |
| A CLI command | `vspagent/cli.py` | a tool |
| Terminal rendering | `vspagent/agent/ui/` | the loop |
| Key storage | `vspagent/auth.py` | config or session files |
| Permission policy | `vspagent/permissions.py` | individual tools |
| Session persistence | `vspagent/session.py` | the REPL |

`cli.py` is wiring only. `agent/loop.py` is UI-agnostic. Tools never call the
network or import Rich.

---

## 🔐 Security rules

1. **Never commit a key.** `.env` is gitignored; tests set
   `VSPAGENT_DISABLE_KEYRING=1` and a temporary `VSPAGENT_AUTH_FILE`.
2. **Never log a secret.** Every tool result, provider error and displayed line
   goes through `security.redact()`.
3. **Never print a full key.** `security.mask_secret()` shows `sk-…abcd`.
4. **No `shell=True`.** The shell tool uses `subprocess.run([bash, "-lc", ...])`
   and strips provider keys from the child environment.
5. **Confine paths.** Every file tool resolves through `Workspace.resolve()`,
   which rejects `..` and symlink escapes.
6. **Ask before mutating.** `PermissionManager` gates writes and shell commands.
   A denied prompt returns a tool result, not an exception.
7. **Never write keys into sessions.** Session files contain messages and token
   usage only.
8. **Redact provider responses.** HTTP error bodies can echo an Authorization
   header; they pass through redaction before becoming an exception.

---

## 🧪 Test pyramid

| File | Covers |
| :--- | :--- |
| `tests/test_security.py` | redaction, mode-600 files, path containment |
| `tests/test_config.py` | defaults, env overrides, custom providers |
| `tests/test_auth.py` | env → keyring → file resolution |
| `tests/test_provider.py` | SSE streaming, tool-call accumulation, retries, errors |
| `tests/test_tools.py` | read/write/edit/search/shell/todo and path escapes |
| `tests/test_permissions.py` | ask, allowlist, yolo |
| `tests/test_session.py` | save/load/latest/compact |
| `tests/test_agent_loop.py` | stream → tool → result → final response |
| `tests/test_cli.py` | subcommands and readable errors |
| `tests/test_install_script.py` | shell syntax and uv flow |
| `tests/test_quality_gate.py` | the gate itself |
| `tests/test_clone_detection.py` | near-duplicate detection |

Add the regression test in the cheapest layer that can catch it.

---

## 🧠 Agent loop contract

1. Append the user message to the session.
2. Stream one model turn. Text goes to the UI as it arrives.
3. If the response has `tool_calls`, append the assistant message, execute each
   tool, append one `role="tool"` message per call, then loop.
4. If there are no tool calls, the turn is complete.
5. Persist the session after the turn.
6. Compact history when it grows beyond the context budget.

The assistant tool-call message and the following tool messages must stay in
order; providers reject a tool result without its matching `tool_call_id`.

---

## 🚫 Out of scope for v4.0

- Colab/Jarvis/daemon commands
- dataset preparation and fine-tuning
- Claude/Gemini native adapters
- full-screen TUI
- Windows installer
- standalone binaries

Add these as separate, explicit changes — not by growing `cli.py`.
