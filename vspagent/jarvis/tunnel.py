"""SSH Tunneling and Port Forwarding manager for remote cloud GPU services."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

TUNNEL_STATE_FILE = Path.home() / ".vspagent" / "tunnels.json"


def _load_tunnels() -> Dict[str, Dict]:
    if not TUNNEL_STATE_FILE.exists():
        return {}
    try:
        return json.loads(TUNNEL_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tunnels(tunnels: Dict[str, Dict]):
    TUNNEL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TUNNEL_STATE_FILE.write_text(json.dumps(tunnels, indent=2), encoding="utf-8")


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def start_ssh_tunnel(
    remote_host: str,
    remote_port: int,
    local_port: Optional[int] = None,
    ssh_user: str = "root",
    ssh_port: int = 22,
    ssh_key: Optional[str] = None,
) -> Dict:
    """Establishes an SSH local port forwarding tunnel in the background.
    
    Forwards: localhost:<local_port> -> <remote_host>:localhost:<remote_port>
    """
    if local_port is None:
        local_port = remote_port

    # Clean dead tunnels first
    tunnels = _load_tunnels()
    active_tunnels = {}
    for k, v in tunnels.items():
        if is_pid_alive(v.get("pid", 0)):
            active_tunnels[k] = v
    tunnels = active_tunnels

    key = f"{local_port}:{remote_port}"
    if key in tunnels and is_pid_alive(tunnels[key]["pid"]):
        return tunnels[key]

    cmd = [
        "ssh",
        "-N",  # Do not execute remote command
        "-f",  # Go to background
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-L", f"{local_port}:127.0.0.1:{remote_port}",
    ]
    if ssh_key:
        cmd.extend(["-i", str(ssh_key)])
    if ssh_port != 22:
        cmd.extend(["-p", str(ssh_port)])

    cmd.append(f"{ssh_user}@{remote_host}")

    # Launch SSH tunnel
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(timeout=10)
    if proc.returncode != 0:
        err_msg = stderr.decode("utf-8").strip() or stdout.decode("utf-8").strip() or "Failed to start tunnel"
        raise RuntimeError(f"SSH Tunnel failed: {err_msg}")

    # Find the PID of the forked SSH process
    # Search for matching command in pgrep
    pid = None
    try:
        pgrep = subprocess.run(
            ["pgrep", "-f", f"{local_port}:127.0.0.1:{remote_port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = [int(p) for p in pgrep.stdout.strip().splitlines() if p.isdigit()]
        if pids:
            pid = pids[-1]
    except Exception:
        pass

    tunnel_info = {
        "local_port": local_port,
        "remote_port": remote_port,
        "remote_host": remote_host,
        "pid": pid,
        "started_at": time.time(),
        "url": f"http://127.0.0.1:{local_port}",
    }
    tunnels[key] = tunnel_info
    _save_tunnels(tunnels)
    return tunnel_info


def stop_ssh_tunnel(local_port: int, remote_port: Optional[int] = None) -> bool:
    """Stops an active SSH tunnel."""
    tunnels = _load_tunnels()
    stopped = False

    for key, info in list(tunnels.items()):
        l_port = info.get("local_port")
        r_port = info.get("remote_port")

        matches = (l_port == local_port)
        if remote_port is not None:
            matches = matches and (r_port == remote_port)

        if matches:
            pid = info.get("pid")
            if pid and is_pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
            tunnels.pop(key, None)
            stopped = True

    _save_tunnels(tunnels)
    return stopped


def list_active_tunnels() -> List[Dict]:
    """Returns list of currently verified alive tunnels."""
    tunnels = _load_tunnels()
    active = []
    updated = {}

    for k, v in tunnels.items():
        pid = v.get("pid")
        if pid and is_pid_alive(pid):
            active.append(v)
            updated[k] = v

    if len(updated) != len(tunnels):
        _save_tunnels(updated)

    return active
