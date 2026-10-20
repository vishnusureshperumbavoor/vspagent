# ⚡ vspagent

[![PyPI version](https://badge.fury.io/py/vspagent.svg)](https://pypi.org/project/vspagent/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vspagent.svg)](https://pypi.org/project/vspagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Universal Google Colab MCP Engine & Remote Cloud GPU Orchestration SDK.**

`vspagent` gives any Python app, web server, or CLI instant access to free/pro Google Colab Cloud GPUs (Tesla T4, A100, V100) via the **Model Context Protocol (MCP)** with **zero local VRAM/GPU requirements**.

---

## 🌟 Key Features

- 🔗 **Zero-Configuration Colab MCP Handshake**: Automatically manages the `colab-mcp` stdio subprocess and JSON-RPC lifecycle.
- 👤 **Cross-Platform Chrome Profile Detection**: Detects all signed-in Google/Gmail accounts across Linux native, WSL, Windows, and macOS, opening pairing in the exact profile chosen.
- 🚀 **Remote GPU Execution**: Programmatically injects, executes, polls, and deletes code cells on Google Colab with structured output and traceback handling.
- 🔌 **Pre-Built Web Framework Adapters**:
  - **FastAPI**: One-line `include_router(get_colab_router())` providing ready-to-use `/colab/status`, `/colab/accounts`, `/colab/connect`, `/colab/execute` endpoints.
  - **Flask**: One-line `register_blueprint(get_colab_blueprint())` supporting synchronous multi-threaded Flask servers.
- 🖥️ **Built-in CLI**: Interactive terminal utility with live account discovery, status dashboards, and code execution.
- 🪶 **Ultra-Lightweight**: Zero local PyTorch, CUDA, or transformers dependencies. Local package size is under 1MB.

---

## 📦 Installation

```bash
pip install vspagent
```

For web framework support:
```bash
# With FastAPI support
pip install "vspagent[fastapi]"

# With Flask support
pip install "vspagent[flask]"

# With all integrations
pip install "vspagent[all]"
```

---

## 🛠️ Quickstart

### 1. Python SDK

```python
import asyncio
from vspagent import ColabClient

async def main():
    colab = ColabClient()
    
    # Connect with preferred Chrome profile (or Default)
    print("Connecting to Google Colab...")
    await colab.connect_browser(profile_directory="Default")
    
    # Wait until user approves pairing in Chrome tab
    await colab.ensure_connected(timeout=60.0)
    print(f"Connected! GPU: {colab.gpu_info}")
    
    # Execute code on remote cloud GPU
    code = """
import torch
print("Hello from Colab GPU:", torch.cuda.get_device_name(0))
    """
    res = await colab.execute_code(code, keep_cell=False)
    print("Output:\n", res["output"])

asyncio.run(main())
```

---

### 2. FastAPI Web Integration (e.g. Vibe-ML-Studio, Vibe-MI-Stdio)

Mount the pre-built router directly onto your FastAPI application:

```python
from fastapi import FastAPI
from vspagent.colab.integrations import get_colab_router

app = FastAPI(title="My GPU-Accelerated Service")

# Mounts /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.include_router(get_colab_router(), prefix="/api")
```

---

### 3. Flask Web Integration (e.g. Karaoke Extractor)

```python
from flask import Flask
from vspagent.colab.integrations import get_colab_blueprint

app = Flask(__name__)

# Mounts /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.register_blueprint(get_colab_blueprint(), url_prefix="/api/colab")
```

---

### 4. Interactive Terminal CLI

```bash
# 1. Discover available Google / Chrome accounts
vspagent colab accounts

# 2. Check connection status and GPU hardware
vspagent colab status

# 3. Interactively connect to Colab tab
vspagent colab connect

# 4. Execute Python code directly on remote Colab GPU
vspagent colab exec -c "import torch; print(torch.cuda.is_available())"

# Or run a complete Python script file
vspagent colab exec -f ./train_decision_model.py
```

---

## 📄 License

MIT License © [Vishnu Suresh Perumbavoor](https://github.com/vishnusureshperumbavoor)
