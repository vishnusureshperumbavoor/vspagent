# Security Policy

`vspagent` is a local coding agent: it holds provider API keys, reads source
code, edits files and runs shell commands. Treat it as a trusted tool with a
small, explicit permission boundary.

## API keys

- Environment variables take priority: `KIMI_API_KEY`, `OPENAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY`,
  `VSPAGENT_API_KEY`.
- Otherwise keys live in the OS keyring (`vspagent auth login`).
- If the keyring is unavailable, the fallback file
  `~/.config/vspagent/auth.json` is written with mode `600`.
- Keys are never written to sessions, logs, generated code or shell commands.
- `security.redact()` runs over provider errors, tool output and every displayed
  line. `security.mask_secret()` is used for status output.

## Workspace confinement

- Every file tool resolves through `Workspace.resolve()`.
- `..`, absolute paths outside the workspace and symlink escapes are rejected.
- The shell tool runs with the workspace as its working directory, but a shell
  can still reach other paths. That is why mutating shell commands require
  approval.

## Command execution

- No `shell=True`.
- `subprocess.run([bash, "-lc", command])` with a timeout, captured streams and
  `stdin=DEVNULL`.
- Provider keys are stripped from the child environment.
- Permission modes: `ask`, `allowlist`, `yolo`. `yolo` is explicit and unsafe by
  design.

## Provider transport

- Only HTTPS (or explicitly configured HTTP for localhost) base URLs.
- No vendor SDKs; one small `httpx` adapter.
- Retries happen only for 429/5xx before any content is consumed.
- Error bodies are redacted before they become exceptions.

## Repository checks

`python scripts/check_quality.py` enforces:

1. file and function size ratchets;
2. import-layer boundaries (providers do not import tools, tools do not import
   HTTP or Rich, the loop does not import the UI, the CLI does not open clients);
3. near-duplicate detection so renamed copies are still caught.

`ruff check .` and `python -m pytest` run in CI on every push.

## Reporting

Open a private GitHub security advisory or contact the maintainer directly. Do
not include API keys, private repository contents or user data in a public issue.
