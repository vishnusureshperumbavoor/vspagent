# ⚡ vspagent

**Terminal coding agent powered by OpenAI-compatible LLM APIs.**

`vspagent` is a local-first coding CLI in the spirit of Codex, Claude Code and
OpenCode. It runs in your terminal, reads and edits files, executes commands with
your approval, keeps resumable sessions, and works with Kimi, OpenAI, DeepSeek,
Qwen, Grok, Gemini's compatibility endpoint and any local OpenAI-compatible
server.

> **v4 is the coding-agent release.** The old Colab/Jarvis harness is gone. It
> remains available in git at tag `v3.3.0-harness` and on PyPI as `vspagent==3.3.0`.
> Fine-tuning and dataset preparation live in [vsptrainagents](../vsptrainagents).

---

## 📦 Install

### One-line install (Linux / macOS)

```bash
curl -fsSL https://github.com/vishnusureshperumbavoor/vspagent/releases/latest/download/install.sh | sh
```

The installer uses [uv](https://docs.astral.sh/uv/), installs into `~/.local/bin`
and never needs root privileges. Pin a release by passing the variable to the
shell, not to `curl`:

```bash
curl -fsSL https://github.com/vishnusureshperumbavoor/vspagent/releases/latest/download/install.sh \
  | VSPAGENT_VERSION=4.0.0 sh
```

If the release asset is not attached yet, use the repo script:

```bash
curl -fsSL https://raw.githubusercontent.com/vishnusureshperumbavoor/vspagent/main/install.sh | sh
```

### pip / uv

```bash
uv tool install vspagent
# or
pip install vspagent
```

Both `vspagent` and `vsp` are installed.

### Uninstall

```bash
bash install.sh --uninstall
# or
uv tool uninstall vspagent
```

---

## 🔑 Add an API key

```bash
vspagent auth login kimi
vspagent auth status
```

Key resolution order:

1. environment variable (`KIMI_API_KEY`, `OPENAI_API_KEY`, …)
2. OS keyring
3. `~/.config/vspagent/auth.json` with mode `600`

Keys are never written to sessions, logs or shell commands.

```bash
export KIMI_API_KEY=...        # CI / one-off use
vspagent auth logout kimi      # remove a stored key
```

Kimi is the default provider and uses Moonshot's OpenAI-compatible endpoint:

```text
https://api.moonshot.ai/v1
```

---

## 🚀 Quickstart

```bash
cd ~/projects/my-app

# interactive coding session
vspagent

# one-shot task
vspagent "find the failing test and fix it"

# choose a model
vspagent --model kimi-k2.7-code "refactor the config loader"

# resume the most recent session
vspagent --continue

# inspect available models
vspagent models
```

Inside an interactive session:

```text
/help                 show commands
/model [name]         show or change the model
/models               list models from the provider
/provider             show provider details
/permissions [mode]   ask | allowlist | yolo
/clear                clear the conversation
/compact              trim old history
/session              session id and token usage
/tools                list tools
/quit                 exit
```

---

## 🧰 Tools

| Tool | Purpose |
| :--- | :--- |
| `read_file` | Read text with line numbers |
| `write_file` | Create or overwrite a file |
| `edit_file` | Exact-string edit with diff preview |
| `list_dir` | List files and directories |
| `glob` | Find files by pattern |
| `grep` | Regex content search |
| `shell` | Run bash with captured output |
| `todo` | Track multi-step work |

Every file operation is confined to the workspace. Paths that resolve outside it
are rejected, including symlink escapes.

---

## 🔐 Permissions

| Mode | Behaviour |
| :--- | :--- |
| `ask` | Read/search auto-approved; writes and shell ask first |
| `allowlist` | File edits and read-only shell commands auto-approved; destructive shell asks |
| `yolo` | Everything runs without prompts |

Set it per run:

```bash
vspagent --permission-mode allowlist
```

or in config:

```toml
[general]
permission_mode = "ask"
```

The shell tool strips provider API keys from the child environment and is never
invoked with `shell=True`.

---

## ⚙️ Configuration

```bash
vspagent config --init     # write ~/.config/vspagent/config.toml
vspagent config            # show the effective config
```

Example:

```toml
[general]
provider = "kimi"
permission_mode = "ask"
max_iterations = 30
timeout = 120.0

[providers.kimi]
type = "openai_compatible"
base_url = "https://api.moonshot.ai/v1"
api_key_env = "KIMI_API_KEY"
model = "kimi-k2.7-code"
auth_style = "bearer"
```

Any OpenAI-compatible server works:

```toml
[providers.local]
type = "openai_compatible"
base_url = "http://127.0.0.1:11434/v1"
api_key_env = "LOCAL_API_KEY"
model = "qwen2.5-coder"
auth_style = "none"
```

Environment overrides: `VSPAGENT_PROVIDER`, `VSPAGENT_MODEL`,
`VSPAGENT_BASE_URL`, `VSPAGENT_PERMISSION_MODE`, `VSPAGENT_CONFIG`.

---

## 🧱 Architecture

| Path | Responsibility |
| :--- | :--- |
| `vspagent/cli.py` | Argument wiring and subcommands |
| `vspagent/config.py` | Config and provider registry |
| `vspagent/auth.py` | Env → keyring → private-file keys |
| `vspagent/security.py` | Redaction, private files, path containment |
| `vspagent/session.py` | Resumable JSON sessions |
| `vspagent/permissions.py` | ask / allowlist / yolo policy |
| `vspagent/agent/loop.py` | Stream → tool calls → repeat |
| `vspagent/agent/providers/` | OpenAI-compatible HTTP adapter |
| `vspagent/agent/tools/` | File, search, shell and todo tools |
| `vspagent/agent/ui/` | Rich + prompt_toolkit REPL |

---

## ✅ Development

```bash
uv venv
uv pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/python scripts/check_quality.py
.venv/bin/python -m pytest
```

CI runs the same three commands. Tests use a fake HTTP transport; no API key or
network access is required.

See [AGENTS.md](AGENTS.md) and [SECURITY.md](SECURITY.md).

---

## 📄 License

MIT License © [Vishnu Suresh Perumbavoor](https://github.com/vishnusureshperumbavoor)
