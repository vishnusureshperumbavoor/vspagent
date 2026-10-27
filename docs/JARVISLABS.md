# ⚡ JarvisLabs Cloud GPU Harness Guide

`vspagent` provides native, first-class orchestration for **JarvisLabs on-demand Cloud GPUs** (NVIDIA A30, A100, H100, RTX 6000 Ada, etc.).

This allows any local application, agent pipeline, or developer workflow to offload heavy deep learning models, training jobs, and real-time inference services to dedicated high-VRAM cloud hardware with **zero local GPU requirements**.

---

## 🚀 Key Features

* **Instant SSH & Key Management:** Automatically detects and configures local private SSH keys (`id_ed25519`, `id_rsa`) for secure, passwordless execution with cloud-hardened host verification.
* **Instance Lifecycle Control:** Programmatically create, adopt, inspect, pause, resume, and terminate GPU instances to strictly control cloud spend.
* **Remote Code & Script Dispatch:** Run inline bash commands or upload local Python scripts and execute them directly on the cloud GPU with real-time streamed logs.
* **Bi-Directional File Synchronization:** High-speed `sync up` and `sync down` between local workspaces and remote `/home` storage via SCP.
* **SSH Port Tunneling (Service Bridging):** Forward any remote GPU service port (e.g. FastAPI, Flask, Gradio, WebSockets on port `8000`, `7860`, `5000`) to your local machine (`http://localhost:8000`). Local frontends and clients can consume remote GPU microservices as if they were running locally.
* **Persistent Daemon Integration:** Manage instances and active port tunnels through the background `vspagent` daemon REST endpoints.

---

## 🔑 Authentication & Configuration

`vspagent` searches for your JarvisLabs API token in the following order:

1. Environment variable: `JARVIS_LABS_API_TOKEN` or `JL_API_KEY`
2. `.env` file in the current working directory or repository root:
   ```env
   JARVIS_LABS_API_TOKEN=your_token_here
   ```
3. Configuration file: `~/.vspagent/jarvislabs.json` or `~/.jarvislabs/config.json`

---

## 🖥️ Command Line Interface (CLI)

All JarvisLabs capabilities are available under `vspagent jarvis`:

### 1. Register / Adopt an Existing Instance
If you already launched an instance from the JarvisLabs web dashboard or have an existing host IP:
```bash
# Adopt by IP address (sets as active GPU worker)
vspagent jarvis adopt 217.18.55.207 --gpu A30 --name worker-1

# View active instance details
vspagent jarvis status

# List all tracked instances
vspagent jarvis list
```

### 2. Remote Command & Script Execution
Execute bash commands or dispatch local Python scripts to the GPU:
```bash
# Run a quick remote shell command
vspagent jarvis exec -c "nvidia-smi"

# Check remote Python and CUDA environment
vspagent jarvis exec -c "python -c 'import torch; print(torch.cuda.get_device_name(0))'"

# Upload a local Python script and run it immediately on the cloud GPU
vspagent jarvis exec -f scripts/run_inference.py --args "--prompt 'Test prompt' --max-tokens 150"
```

### 3. File Transfer (`sync`)
Synchronize code, datasets, model checkpoints, and generated audio/video artifacts:
```bash
# Upload a local directory or file to remote /home
vspagent jarvis sync up ./models /home/models

# Download generated outputs from remote GPU to local directory
vspagent jarvis sync down /home/outputs ./local_outputs
```

### 4. Interactive SSH
```bash
# Open an interactive SSH session directly into the active GPU instance
vspagent jarvis ssh

# Print the full connection string
vspagent jarvis ssh --print-only
```

### 5. Port Tunneling (Serve Remote Microservices Locally)
When running a remote inference API, speech synthesis server, or web UI on the cloud GPU:
```bash
# Forward remote port 8000 to localhost:8000
vspagent jarvis tunnel 8000

# Forward remote port 7860 (Gradio) to local port 7860
vspagent jarvis tunnel 7860

# List all active background SSH tunnels
vspagent jarvis tunnels

# Stop a tunnel on local port 8000
vspagent jarvis untunnel 8000
```

### 6. Cost Control: Pause, Resume, and Destroy
```bash
# Pause instance to stop compute billing (retains /home storage at minimal cost)
vspagent jarvis pause

# Resume paused instance
vspagent jarvis resume

# Permanently destroy instance to stop all charges
vspagent jarvis destroy -y
```

---

## 🐍 Python SDK Integration

Any Python application or agent pipeline can import and control the GPU harness directly:

### Basic Remote Execution
```python
from vspagent.jarvis import JarvisLabsClient

client = JarvisLabsClient()

# 1. Inspect active GPU instance
instance = client.get_active_instance()
print(f"Connected to: {instance['name']} ({instance['gpu_type']}) at {instance['host']}")

# 2. Execute bash command with live streaming output
exit_code, output = client.exec("nvidia-smi")

# 3. Upload and execute a script
exit_code, output = client.run_script(
    local_path="scripts/audio_pipeline.py",
    script_args="--input sample.wav --model large",
)
```

### Microservice Bridging via Port Tunnel
If your cloud GPU runs a real-time service (e.g. a FastAPI speech synthesis endpoint or WebSocket streaming server):

```python
from vspagent.jarvis import JarvisLabsClient
import requests

client = JarvisLabsClient()

# 1. Start the remote service in the background
client.exec("nohup python /home/server.py --port 8000 > /home/server.log 2>&1 &")

# 2. Establish local SSH port forward: localhost:8000 -> remote:8000
tunnel_info = client.tunnel(remote_port=8000, local_port=8000)
print(f"Service tunneled to: {tunnel_info['url']}")

# 3. Local applications can now call http://localhost:8000 directly
response = requests.get("http://localhost:8000/health")
print("Remote GPU Service Status:", response.json())

# 4. Stop tunnel when done
client.stop_tunnel(8000)
```

---

## 🌐 Daemon REST API Endpoints

When running `vspagent serve` or the background daemon, the following HTTP routes are available:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/jarvis/instances` | List all tracked and active GPU instances. |
| `GET` | `/jarvis/status` | Get metadata for the currently active GPU instance. |
| `GET` | `/jarvis/tunnels` | List all active SSH port forwarding tunnels. |
| `POST` | `/jarvis/adopt` | Register an instance (`{"host": "...", "gpu": "A30"}`). |
| `POST` | `/jarvis/exec` | Run a remote command (`{"command": "...", "workdir": "/home"}`). |
| `POST` | `/jarvis/tunnel` | Start a port forward (`{"remote_port": 8000, "local_port": 8000}`). |
| `POST` | `/jarvis/untunnel` | Stop a port forward (`{"local_port": 8000}`). |
| `POST` | `/jarvis/pause` | Pause an instance (`{"id": "..."}`). |
| `POST` | `/jarvis/resume` | Resume an instance (`{"id": "..."}`). |
| `POST` | `/jarvis/destroy` | Terminate an instance (`{"id": "..."}`). |
