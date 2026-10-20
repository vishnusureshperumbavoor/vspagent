# ⚡ vspagent

[![PyPI version](https://badge.fury.io/py/vspagent.svg)](https://pypi.org/project/vspagent/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vspagent.svg)](https://pypi.org/project/vspagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Agent Orchestrator & Cloud GPU SDK.**

`vspagent` is a lightweight Python agent orchestrator that connects any AI application, web backend, or developer CLI to Google Colab Cloud GPUs (Tesla T4, A100, V100) via the **Model Context Protocol (MCP)** with **zero local VRAM/GPU requirements**.

Whether you are orchestrating fine-tuning jobs (ModernBERT, Laya), running deep learning inference (TotalSegmentator, MedGemma), or dispatching heavy audio/vision pipelines (Demucs, Seed-VC), `vspagent` orchestrates the entire cloud GPU lifecycle seamlessly.

---

## 🌟 Key Capabilities

- 🤖 **Agentic MCP Orchestration**: Manages the `colab-mcp` stdio daemon, JSON-RPC protocol, and tool invocations behind clean, Pythonic abstractions.
- 👤 **Intelligent Account & Profile Routing**: Automatically detects signed-in Google/Chrome profiles across Linux, WSL, Windows, and macOS, dispatching browser pairing to the desired Google account.
- 🚀 **Remote Cloud GPU Dispatch**: Injects, monitors, and cleans up remote execution payloads on Colab runtimes with real-time log streaming and traceback extraction.
- 📁 **Automated Cloud File Transfer**: High-speed, chunked bidirectional file synchronization between local storage and remote Colab file systems.
- 🔌 **Drop-in Web Framework Adapters**:
  - **FastAPI**: One-line `app.include_router(get_colab_router())` providing ready-to-use `/colab/status`, `/colab/accounts`, `/colab/connect`, `/colab/execute` endpoints.
  - **Flask**: One-line `app.register_blueprint(get_colab_blueprint())` supporting synchronous multi-threaded Flask backends.
- 🖥️ **Interactive Terminal CLI**: Built-in developer CLI with rich tables, live account discovery, connection health checks, and direct code dispatch.
- 🪶 **Zero-Dependency Local Footprint**: Keeps local environments clean (<1MB). Heavy machine learning dependencies (`torch`, `cuda`, `transformers`) stay isolated on the remote cloud GPU.

---

## 📦 Installation

```bash
pip install vspagent
```

### Framework Extensions:
```bash
# With FastAPI support
pip install "vspagent[fastapi]"

# With Flask support
pip install "vspagent[flask]"

# With all adapters
pip install "vspagent[all]"
```

---

## 🛠️ Quickstart

### 1. Python SDK — Direct Agent Orchestration

```python
import asyncio
from vspagent import ColabClient

async def main():
    colab = ColabClient()
    
    # 1. Orchestrate pairing with the user's preferred Google account
    print("Initiating Colab agent handshake...")
    await colab.connect_browser(profile_directory="Default")
    
    # 2. Await tab authorization in Chrome
    await colab.ensure_connected(timeout=60.0)
    print(f"Connected to Cloud GPU: {colab.gpu_info}")
    
    # 3. Dispatch remote GPU execution
    payload = """
import torch
print("Agent GPU Ready:", torch.cuda.get_device_name(0))
    """
    res = await colab.execute_code(payload, keep_cell=False)
    print("Remote Output:\n", res["output"])

asyncio.run(main())
```

---

### 2. FastAPI Web Orchestration (e.g. Vibe-ML-Studio, Vibe-MI-Stdio)

Mount the orchestrator directly into your FastAPI application:

```python
from fastapi import FastAPI
from vspagent.colab.integrations import get_colab_router

app = FastAPI(title="My GPU-Accelerated Service")

# Exposes /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.include_router(get_colab_router(), prefix="/api")
```

---

### 3. Flask Web Orchestration (e.g. Karaoke Extractor)

```python
from flask import Flask
from vspagent.colab.integrations import get_colab_blueprint

app = Flask(__name__)

# Exposes /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.register_blueprint(get_colab_blueprint(), url_prefix="/api/colab")
```

---

### 4. Interactive Terminal CLI

```bash
# Discover available Google / Chrome profiles
vspagent colab accounts

# Inspect Colab MCP orchestrator status & GPU hardware
vspagent colab status

# Interactively pair terminal session with Colab tab
vspagent colab connect

# Dispatch inline code to Colab GPU
vspagent colab exec -c "import torch; print(torch.cuda.is_available())"

# Dispatch a local Python script to remote Colab GPU
vspagent colab exec -f ./train_model.py
```

---

## 📄 License

MIT License © [Vishnu Suresh Perumbavoor](https://github.com/vishnusureshperumbavoor)
