# ⚡ vspagent

[![PyPI version](https://badge.fury.io/py/vspagent.svg)](https://pypi.org/project/vspagent/)
[![Python Versions](https://img.shields.io/pypi/pyversions/vspagent.svg)](https://pypi.org/project/vspagent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Universal Hybrid Agent Harness & Cloud GPU Execution Runtime.**

`vspagent` is a lightweight, extensible agent harness that bridges local development environments, web backends, and AI coding agents to high-performance Cloud GPUs with **zero local VRAM/GPU requirements**:
* **Google Colab via Model Context Protocol (MCP)** (Tesla T4, A100, V100)
* **JarvisLabs On-Demand Dedicated Cloud GPUs** (NVIDIA A30, A100, H100, RTX 6000 Ada)

Whether you are fine-tuning models, running deep learning inference, or dispatching heavy real-time audio/vision pipelines, `vspagent` acts as your unified execution harness—managing background daemons, MCP protocol bridges, cloud GPU instances, SSH port tunnels, and file synchronization seamlessly.

---

## 🌟 Key Capabilities

### Google Colab MCP Runtime
- 🤖 **Agentic MCP Runtime Harness**: Manages the `colab-mcp` stdio daemon, JSON-RPC protocol, tool registry, and background execution behind clean, Pythonic abstractions.
- ⚙️ **Persistent Background Daemon**: Auto-spawning local daemon that preserves browser pairings, tool availability, and GPU sessions across separate terminal commands.
- 👤 **Intelligent Account & Profile Routing**: Automatically detects signed-in Google/Chrome profiles across Linux, WSL, Windows, and macOS, dispatching browser pairing to the desired Google account.
- 🚀 **Remote Cloud GPU Dispatch**: Injects, monitors, and cleans up remote execution payloads on Colab runtimes with real-time log streaming and traceback extraction.

### JarvisLabs Cloud GPU Harness
- ⚡ **Dedicated GPU Orchestration**: Adopt, provision, pause, resume, and terminate on-demand cloud GPU instances (A30, A100, H100) to optimize cloud compute spend.
- 🔒 **Cloud-Hardened SSH Execution**: Run remote shell commands or dispatch local Python scripts with automated SSH key detection and real-time streaming output.
- 🌐 **SSH Port Tunneling (Service Bridging)**: Forward remote GPU microservices (FastAPI, Flask, Gradio, WebSockets on ports `8000`, `7860`, `5000`) directly to `http://localhost:8000`. Local clients and web frontends consume cloud models as if running locally.
- 📁 **High-Speed Bi-Directional Sync**: Upload code and datasets or download model artifacts and outputs via SCP.
- 📖 **Comprehensive Guide**: See [docs/JARVISLABS.md](docs/JARVISLABS.md) for complete reference.

### Universal Web & Developer Tooling
- 🔌 **Drop-in Web Framework Adapters**: Ready-to-use FastAPI routers and Flask blueprints for zero-friction service integration.
- 🖥️ **Interactive Terminal CLI**: Built-in developer CLI with rich tables, connection health checks, daemon management, and direct code dispatch (`vspagent colab`, `vspagent jarvis`, `vspagent daemon`).
- 🪶 **Zero-Dependency Local Footprint**: Keeps local environments clean (<1MB). Heavy machine learning dependencies (`torch`, `cuda`, `transformers`) stay isolated on the remote cloud GPU.

---

## 📦 Installation

```bash
pip install vspagent
# or using uv:
uv tool install vspagent
```

---

## 🛠️ Quickstart

### 1. Python SDK — Direct Agent Harness

```python
import asyncio
from vspagent import ColabClient

async def main():
    colab = ColabClient()
    
    # 1. Connect harness with the user's preferred Google account
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

### 2. FastAPI Web Harness (e.g. Vibe-ML-Studio, Vibe-MI-Stdio)

Mount the harness router directly into your FastAPI application:

```python
from fastapi import FastAPI
from vspagent.colab.integrations import get_colab_router

app = FastAPI(title="My GPU-Accelerated Service")

# Exposes /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.include_router(get_colab_router(), prefix="/api")
```

---

### 3. Flask Web Harness (e.g. Karaoke Extractor)

```python
from flask import Flask
from vspagent.colab.integrations import get_colab_blueprint

app = Flask(__name__)

# Exposes /colab/status, /colab/accounts, /colab/connect, /colab/execute
app.register_blueprint(get_colab_blueprint(), url_prefix="/api/colab")
```

---

### 4. JarvisLabs Cloud GPU Harness

#### Python SDK:
```python
from vspagent.jarvis import JarvisLabsClient

client = JarvisLabsClient()

# 1. Execute remote commands on GPU
code, output = client.exec("nvidia-smi")

# 2. Upload and run a script remotely
client.run_script("scripts/train.py", script_args="--epochs 5")

# 3. Tunnel remote FastAPI/Gradio microservice port to localhost:8000
tunnel = client.tunnel(remote_port=8000, local_port=8000)
print(f"Service live at: {tunnel['url']}")
```

#### CLI:
```bash
# Register an active instance by IP
vspagent jarvis adopt 217.18.55.207 --gpu A30

# Check instance specs & connection status
vspagent jarvis status

# Run commands or dispatch Python scripts directly to Cloud GPU
vspagent jarvis exec -c "nvidia-smi"
vspagent jarvis exec -f ./inference.py

# Forward remote microservice port to localhost (e.g. port 8000)
vspagent jarvis tunnel 8000

# Pause instance to stop compute billing
vspagent jarvis pause
```

---

### 5. Google Colab MCP CLI & Daemon

```bash
# Discover available Google / Chrome profiles
vspagent colab accounts

# Pair terminal session with Colab tab (persisted in background daemon)
vspagent colab connect

# Inspect Colab MCP harness status & GPU hardware
vspagent colab status

# Dispatch inline code to Colab GPU
vspagent colab exec -c "import torch; print(torch.cuda.is_available())"

# Dispatch a local Python script to remote Colab GPU
vspagent colab exec -f ./train_model.py

# Daemon management
vspagent daemon status
vspagent daemon logs
vspagent daemon stop
```

---

## 📄 License

MIT License © [Vishnu Suresh Perumbavoor](https://github.com/vishnusureshperumbavoor)
