# vspagent: Long-Term Agent Harness Architecture & Roadmap

This document outlines the strategic roadmap for evolving `vspagent` into a modular, production-grade agent harness, with the unique advantage of **hybrid local development and zero-local-GPU cloud execution** via Google Colab.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │                 User Clients                 │
                      │  • Interactive TUI (`vspagent`)              │
                      │  • One-Shot CLI (`vspagent run`, `exec`)     │
                      │  • External UI (Vibe-ML-Studio / Web)        │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTP / SSE Events
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │         vspagent Daemon (Core Harness)       │
                      │                                              │
                      │  ┌────────────────────────────────────────┐  │
                      │  │ Session & Event Engine (SQLite / SSE)  │  │
                      │  └───────────────────┬────────────────────┘  │
                      │                      │                       │
                      │  ┌───────────────────▼────────────────────┐  │
                      │  │   Autonomous Agent Loop (LiteLLM)      │  │
                      │  └───────────────────┬────────────────────┘  │
                      │                      │                       │
                      │  ┌───────────────────▼────────────────────┐  │
                      │  │ Tool Registry & Permissions Manager    │  │
                      │  └───────────┬─────────────────┬──────────┘  │
                      └──────────────┼─────────────────┼─────────────┘
                                     │                 │
                ┌────────────────────▼────┐       ┌────▼────────────────────────┐
                │   Local Workspace Tools │       │   Remote Cloud GPU Harness  │
                │  • read_file, edit_file │       │  • ColabMCPClient           │
                │  • write_file, patch    │       │  • colab_execute_code       │
                │  • bash, ripgrep, glob  │       │  • chunked b64 file sync    │
                └─────────────────────────┘       └─────────────────────────────┘
```

---

## Phase Status Summary

- [x] **Phase 1: Persistent Background Daemon & Client-Server Bridge (Completed)**
  - Local HTTP daemon listening on `127.0.0.1:4096` (`~/.vspagent/`).
  - Persistent lifecycle for `colab-mcp` subprocess across terminal sessions.
  - Zero-dependency implementation with auto-spawning, health checks, PID management, and log tracking.
  - Subcommands: `vspagent daemon {status,start,stop,restart,logs}`, `vspagent serve`, `vspagent colab disconnect`.

- [ ] **Phase 2: Hybrid Tool Registry & MCP Extensibility**
- [ ] **Phase 3: Autonomous Agent Loop, Session Persistence & Event Bus**
- [ ] **Phase 4: Interactive Terminal UI (Textual TUI)**
- [ ] **Phase 5: Self-Hosted Web Dashboard & IDE Extension Bridge**

---

## Detailed Phase Breakdown

### Phase 2: Hybrid Tool Registry & MCP Extensibility

#### 2.1 Tool Registry Interface
Create `vspagent/tools/` defining a standard tool signature:
```python
class BaseTool(ABC):
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    requires_approval: bool = False

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass
```

#### 2.2 Core Local Tools
- **`read_file`**: Read files with line-range pagination and syntax detection.
- **`edit_file` / `apply_diff`**: Targeted replacement or unified diff applicator with AST validation.
- **`write_file`**: Safe file creation with directory resolution.
- **`glob` / `grep`**: Fast pattern matching and semantic code search via `ripgrep`.
- **`bash`**: Sandboxed command execution with timeout and streaming stdout/stderr.

#### 2.3 Cloud GPU Tools (Colab Integration)
- **`colab_exec`**: High-performance remote GPU execution of PyTorch, JAX, or training scripts.
- **`colab_sync_push`**: Upload local project folders or checkpoints to `/content` on Colab via chunked base64 slices.
- **`colab_sync_pull`**: Retrieve model weights, `.onnx` models, and artifacts from Colab to local disk.
- **`colab_gpu_stat`**: Live GPU temperature, compute utilization, and VRAM monitoring (`nvidia-smi` JSON polling).

#### 2.4 Multi-MCP Server Host
- Expand the JSON-RPC stdio transport in `vspagent/colab/client.py` into a generic MCP host.
- Support reading `~/.vspagent/mcp.json` to attach external MCP servers (GitHub, Postgres, Brave Search, etc.) alongside Colab.

---

### Phase 3: Autonomous Agent Loop, Session Persistence & Event Bus

#### 3.1 Multi-Provider LLM Engine
- Integrate a vendor-neutral LLM abstraction layer (`litellm` or lightweight direct clients for Anthropic Claude 3.5/3.7, OpenAI GPT-4o, Google Gemini 2.0 / 2.5, and local Ollama/vLLM models).
- Support system prompt customization and dynamic system prompts (project instructions, `AGENTS.md`, `CLAUDE.md`).

#### 3.2 The ReAct / Tool-Use Loop
- Streaming turn loop with token generation and function calling:
  1. Stream assistant reasoning and thought blocks.
  2. Parse tool calls into structured invocation events.
  3. Validate against user permissions (auto-allow read tools; prompt or check policy for destructive bash commands).
  4. Dispatch to either local filesystem or remote Colab GPU.
  5. Feed tool outputs back into conversation context.
  6. Repeat until task completion.

#### 3.3 Event Bus & Streaming Server (SSE)
- Add Server-Sent Events (SSE) endpoint to `vspagent/daemon.py`:
  - `GET /sessions/{session_id}/events`
  - Event types: `token`, `thought`, `tool_call_start`, `tool_call_result`, `gpu_status`, `error`, `done`.
- Enables multiple clients to observe and control the agent in real time.

#### 3.4 Session & Checkpoint Storage
- SQLite-backed state in `~/.vspagent/sessions.db`:
  - Conversation messages and token metrics.
  - File snapshots and undo history.
  - Colab notebook execution IDs and artifacts.
- Command: `vspagent --resume [session_id]`.

---

### Phase 4: Interactive Terminal UI (Textual TUI)

#### 4.1 Modern Textual Interface
- Launchable with `vspagent` (without arguments) in any terminal.
- Split-pane layout:
  - **Top Bar**: Model selector, token count, connection badge, live Colab GPU VRAM gauge.
  - **Main Viewport**: Scrollable chat, syntax-highlighted code blocks, collapsible tool executions, and diff previews.
  - **Bottom Input**: Multi-line command input with slash-command autocompletion and file mentions (`@file`).

#### 4.2 Built-in Slash Commands
- `/colab connect [profile]` — trigger Colab pairing directly from TUI.
- `/colab gpu` — display remote GPU telemetry.
- `/model <name>` — switch LLM model on the fly.
- `/compact` — summarize conversation history to free context window.
- `/diff` — review pending file changes before applying.
- `/undo` — revert last tool file modifications.

---

### Phase 5: Self-Hosted Web Dashboard & Studio Integration

#### 5.1 Web UI Companion
- Embedded lightweight web interface served at `http://127.0.0.1:4096/` when running `vspagent serve`.
- Complete visualization of agent trajectories, generated artifacts, and Colab GPU metrics.

#### 5.2 Direct Vibe-ML-Studio Integration
- First-class API client package for [Vibe-ML-Studio](file:///home/vishnusureshperumbavoor/Desktop/test/Vibe-ML-Studio).
- Fine-tuning orchestration: Vibe-ML-Studio dispatches training jobs to `vspagent`, which automatically handles Colab runtime pairing, dataset staging, GPU training execution, and checkpoint downloading.
