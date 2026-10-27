"""JarvisLabs Cloud GPU Client & Agent Harness."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vspagent.jarvis.tunnel import (
    list_active_tunnels,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)

CONFIG_DIR = Path.home() / ".vspagent"
STATE_FILE = CONFIG_DIR / "jarvislabs_instances.json"
CREDENTIALS_FILE = CONFIG_DIR / "jarvislabs.json"


def _find_env_token() -> Optional[str]:
    """Search environment, .env files, and local config for JarvisLabs API token."""
    # 1. Environment variables
    for key in ("JARVIS_LABS_API_TOKEN", "JL_API_KEY", "JARVISLABS_API_KEY", "JARVISLABS_TOKEN"):
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()

    # 2. Search .env up directory tree and standard locations
    search_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path.home() / ".vspagent" / ".env",
    ]
    # Check parent packages if any
    try:
        pkg_env = Path(__file__).resolve().parent.parent.parent / ".env"
        search_paths.append(pkg_env)
    except Exception:
        pass

    for p in search_paths:
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k in ("JARVIS_LABS_API_TOKEN", "JL_API_KEY", "JARVISLABS_API_KEY") and v:
                            return v
            except Exception:
                pass

    # 3. Dedicated credentials file
    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if data.get("token"):
                return data["token"]
        except Exception:
            pass

    # 4. ~/.jarvislabs/config.json if user used official CLI setup
    jl_config = Path.home() / ".jarvislabs" / "config.json"
    if jl_config.exists():
        try:
            data = json.loads(jl_config.read_text(encoding="utf-8"))
            if data.get("jwt") or data.get("token") or data.get("api_key"):
                return data.get("jwt") or data.get("token") or data.get("api_key")
        except Exception:
            pass

    return None


def _find_default_ssh_key() -> Optional[str]:
    """Auto-detect available local SSH private key."""
    home_ssh = Path.home() / ".ssh"
    for candidate in ("id_ed25519", "id_rsa", "id_ecdsa"):
        key_path = home_ssh / candidate
        if key_path.exists():
            return str(key_path)
    return None


class JarvisLabsClient:
    """Universal client for managing JarvisLabs GPU instances, remote SSH execution, and port forwarding."""

    def __init__(self, token: Optional[str] = None, ssh_key: Optional[str] = None):
        self.token = token or _find_env_token()
        self.ssh_key = ssh_key or _find_default_ssh_key()
        self._sdk_client = None
        self._init_sdk_if_available()

    def _init_sdk_if_available(self):
        """Attempts to initialize the official jarvislabs Python SDK if installed."""
        if not self.token:
            return
        try:
            import jarvislabs
            # Provide token via environment for official SDK compatibility
            os.environ["JL_API_KEY"] = self.token
            self._sdk_client = jarvislabs.Client()
        except Exception:
            self._sdk_client = None

    def _load_saved_instances(self) -> Dict[str, Dict]:
        if not STATE_FILE.exists():
            return {}
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_saved_instances(self, data: Dict[str, Dict]):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def register_instance(
        self,
        host: str,
        machine_id: Optional[str] = None,
        name: str = "gpu-instance",
        user: str = "root",
        port: int = 22,
        gpu_type: str = "Unknown",
        status: str = "Running",
        jupyter_url: Optional[str] = None,
        set_active: bool = True,
    ) -> Dict:
        """Register or adopt an existing running JarvisLabs instance by IP/Host."""
        if not machine_id:
            machine_id = f"inst-{host.replace('.', '-')}"

        info = {
            "machine_id": str(machine_id),
            "name": name,
            "host": host,
            "user": user,
            "port": port,
            "gpu_type": gpu_type,
            "status": status,
            "jupyter_url": jupyter_url,
            "registered_at": time.time(),
            "ssh_command": f"ssh -o StrictHostKeyChecking=no {user}@{host}" + (f" -p {port}" if port != 22 else ""),
        }

        saved = self._load_saved_instances()
        saved[str(machine_id)] = info
        if set_active or "active_id" not in saved:
            saved["active_id"] = str(machine_id)
        self._save_saved_instances(saved)
        return info

    def get_active_instance(self) -> Optional[Dict]:
        """Retrieve the primary/active instance configuration."""
        saved = self._load_saved_instances()
        active_id = saved.get("active_id")
        if active_id and active_id in saved and isinstance(saved[active_id], dict):
            return saved[active_id]

        # Fallback to first available instance
        for k, v in saved.items():
            if k != "active_id" and isinstance(v, dict):
                return v
        return None

    def set_active_instance(self, machine_id: str) -> bool:
        """Set an instance as the active default."""
        saved = self._load_saved_instances()
        if machine_id in saved:
            saved["active_id"] = machine_id
            self._save_saved_instances(saved)
            return True
        return False

    def list_instances(self) -> List[Dict]:
        """List all instances from the official SDK (if available) and locally tracked state."""
        results = []
        seen_ids = set()

        # 1. Query official SDK if installed and configured
        if self._sdk_client:
            try:
                remote_list = self._sdk_client.instances.list()
                for inst in remote_list:
                    mid = str(getattr(inst, "machine_id", getattr(inst, "id", "")))
                    host = getattr(inst, "ip", getattr(inst, "host", ""))
                    ssh_cmd = getattr(inst, "ssh_command", "")
                    port = 22
                    user = "root"
                    if ssh_cmd:
                        match = re.search(r"(\w+)@([\w\.\-]+)(?:\s+-p\s+(\d+))?", ssh_cmd)
                        if match:
                            user = match.group(1)
                            host = match.group(2)
                            if match.group(3):
                                port = int(match.group(3))

                    item = {
                        "machine_id": mid,
                        "name": getattr(inst, "name", "remote-gpu"),
                        "host": host,
                        "user": user,
                        "port": port,
                        "gpu_type": getattr(inst, "gpu_type", getattr(inst, "gpu", "GPU")),
                        "status": getattr(inst, "status", "Unknown"),
                        "jupyter_url": getattr(inst, "url", getattr(inst, "jupyter_url", None)),
                        "ssh_command": ssh_cmd or f"ssh {user}@{host}",
                    }
                    results.append(item)
                    seen_ids.add(mid)
            except Exception:
                pass

        # 2. Add locally registered instances
        saved = self._load_saved_instances()
        for k, v in saved.items():
            if k == "active_id" or not isinstance(v, dict):
                continue
            if k not in seen_ids:
                results.append(v)

        return results

    def create_instance(
        self,
        gpu_type: str = "A30",
        name: str = "gpu-worker",
        hdd: int = 25,
        template: str = "pytorch",
    ) -> Dict:
        """Provision a new GPU instance on JarvisLabs."""
        if not self._sdk_client:
            raise RuntimeError(
                "JarvisLabs SDK is not initialized. Please ensure JARVIS_LABS_API_TOKEN is set "
                "or install the SDK via `pip install jarvislabs`."
            )

        inst = self._sdk_client.instances.create(
            gpu_type=gpu_type,
            name=name,
            hdd=hdd,
            template=template,
        )
        mid = str(getattr(inst, "machine_id", getattr(inst, "id", "")))
        ssh_cmd = getattr(inst, "ssh_command", "")
        host = getattr(inst, "ip", getattr(inst, "host", ""))
        user = "root"
        port = 22
        if ssh_cmd:
            match = re.search(r"(\w+)@([\w\.\-]+)(?:\s+-p\s+(\d+))?", ssh_cmd)
            if match:
                user = match.group(1)
                host = match.group(2)
                if match.group(3):
                    port = int(match.group(3))

        return self.register_instance(
            host=host,
            machine_id=mid,
            name=name,
            user=user,
            port=port,
            gpu_type=gpu_type,
            status="Running",
            jupyter_url=getattr(inst, "url", None),
        )

    def pause(self, machine_id: Optional[str] = None) -> bool:
        """Pause instance to halt compute billing."""
        target_id = machine_id
        if not target_id:
            active = self.get_active_instance()
            target_id = active.get("machine_id") if active else None

        if not target_id:
            raise ValueError("No instance ID specified and no active instance configured.")

        if self._sdk_client:
            try:
                res = self._sdk_client.instances.pause(target_id)
                self._update_saved_status(target_id, "Paused")
                return bool(res)
            except Exception as e:
                raise RuntimeError(f"Failed to pause instance via SDK: {e}")

        # Update local status tracker
        self._update_saved_status(target_id, "Paused")
        return True

    def resume(self, machine_id: Optional[str] = None, gpu_type: Optional[str] = None) -> bool:
        """Resume a paused instance."""
        target_id = machine_id
        if not target_id:
            active = self.get_active_instance()
            target_id = active.get("machine_id") if active else None

        if not target_id:
            raise ValueError("No instance ID specified and no active instance configured.")

        if self._sdk_client:
            try:
                kwargs = {}
                if gpu_type:
                    kwargs["gpu_type"] = gpu_type
                res = self._sdk_client.instances.resume(target_id, **kwargs)
                self._update_saved_status(target_id, "Running")
                return bool(res)
            except Exception as e:
                raise RuntimeError(f"Failed to resume instance via SDK: {e}")

        self._update_saved_status(target_id, "Running")
        return True

    def destroy(self, machine_id: Optional[str] = None) -> bool:
        """Permanently delete instance and stop all charges."""
        target_id = machine_id
        if not target_id:
            active = self.get_active_instance()
            target_id = active.get("machine_id") if active else None

        if not target_id:
            raise ValueError("No instance ID specified and no active instance configured.")

        success = True
        if self._sdk_client:
            try:
                self._sdk_client.instances.destroy(target_id)
            except Exception as e:
                raise RuntimeError(f"Failed to destroy instance via SDK: {e}")

        # Remove from local registry
        saved = self._load_saved_instances()
        saved.pop(str(target_id), None)
        if saved.get("active_id") == str(target_id):
            saved.pop("active_id", None)
        self._save_saved_instances(saved)
        return success

    def _update_saved_status(self, machine_id: str, new_status: str):
        saved = self._load_saved_instances()
        if machine_id in saved and isinstance(saved[machine_id], dict):
            saved[machine_id]["status"] = new_status
            self._save_saved_instances(saved)

    def _resolve_connection_details(self, instance_id: Optional[str] = None) -> Tuple[str, str, int]:
        """Returns (host, user, port) for the specified or active instance."""
        inst = None
        if instance_id:
            saved = self._load_saved_instances()
            inst = saved.get(str(instance_id))
        if not inst:
            inst = self.get_active_instance()

        if not inst:
            raise ValueError("No active or specified JarvisLabs instance found to connect.")

        host = inst.get("host")
        user = inst.get("user", "root")
        port = int(inst.get("port", 22))
        if not host:
            raise ValueError("Instance has no valid host/IP address.")
        return host, user, port

    def exec(
        self,
        command: str,
        instance_id: Optional[str] = None,
        workdir: str = "/home",
        stream: bool = True,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, str]:
        """Execute a remote bash command over SSH on the GPU instance."""
        host, user, port = self._resolve_connection_details(instance_id)

        env_prefix = ""
        if env_vars:
            exports = [f"export {k}='{v}'" for k, v in env_vars.items()]
            env_prefix = " && ".join(exports) + " && "

        full_remote_cmd = f"{env_prefix}cd {workdir} && {command}"

        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ServerAliveInterval=30",
        ]
        if self.ssh_key:
            ssh_cmd.extend(["-i", self.ssh_key])
        if port != 22:
            ssh_cmd.extend(["-p", str(port)])

        ssh_cmd.extend([f"{user}@{host}", full_remote_cmd])

        if stream:
            proc = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            output_lines = []
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    output_lines.append(line)
            proc.wait()
            return proc.returncode, "".join(output_lines)
        else:
            res = subprocess.run(ssh_cmd, capture_output=True, text=True)
            return res.returncode, res.stdout + res.stderr

    def run_script(
        self,
        local_path: str,
        instance_id: Optional[str] = None,
        remote_dir: str = "/home",
        script_args: Optional[str] = None,
    ) -> Tuple[int, str]:
        """Upload a local Python script and execute it immediately on the GPU."""
        path = Path(local_path)
        if not path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        # Upload script to remote directory
        self.sync_up(str(path), remote_path=remote_dir, instance_id=instance_id)

        # Run via remote python
        remote_file_name = path.name
        cmd = f"python {remote_file_name}"
        if script_args:
            cmd += f" {script_args}"

        return self.exec(cmd, instance_id=instance_id, workdir=remote_dir, stream=True)

    def sync_up(
        self,
        local_path: str,
        remote_path: str = "/home",
        instance_id: Optional[str] = None,
    ) -> bool:
        """Upload local file or directory to remote GPU instance via SCP."""
        host, user, port = self._resolve_connection_details(instance_id)
        local_p = Path(local_path)
        if not local_p.exists():
            raise FileNotFoundError(f"Source path does not exist: {local_path}")

        scp_cmd = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
        if local_p.is_dir():
            scp_cmd.append("-r")
        if self.ssh_key:
            scp_cmd.extend(["-i", self.ssh_key])
        if port != 22:
            scp_cmd.extend(["-P", str(port)])

        scp_cmd.extend([str(local_p), f"{user}@{host}:{remote_path}"])
        res = subprocess.run(scp_cmd)
        return res.returncode == 0

    def sync_down(
        self,
        remote_path: str,
        local_path: str,
        instance_id: Optional[str] = None,
    ) -> bool:
        """Download remote files or directories to local machine via SCP."""
        host, user, port = self._resolve_connection_details(instance_id)

        scp_cmd = ["scp", "-r", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
        if self.ssh_key:
            scp_cmd.extend(["-i", self.ssh_key])
        if port != 22:
            scp_cmd.extend(["-P", str(port)])

        scp_cmd.extend([f"{user}@{host}:{remote_path}", str(local_path)])
        res = subprocess.run(scp_cmd)
        return res.returncode == 0

    def tunnel(
        self,
        remote_port: int,
        local_port: Optional[int] = None,
        instance_id: Optional[str] = None,
    ) -> Dict:
        """Forward a remote service port (e.g. FastAPI / Gradio / WebSocket) to localhost."""
        host, user, port = self._resolve_connection_details(instance_id)
        return start_ssh_tunnel(
            remote_host=host,
            remote_port=remote_port,
            local_port=local_port,
            ssh_user=user,
            ssh_port=port,
            ssh_key=self.ssh_key,
        )

    def stop_tunnel(self, local_port: int) -> bool:
        """Stop an active port forwarding tunnel."""
        return stop_ssh_tunnel(local_port)

    def list_tunnels(self) -> List[Dict]:
        """List currently active port forwarding tunnels."""
        return list_active_tunnels()

    def interactive_ssh(self, instance_id: Optional[str] = None):
        """Open an interactive terminal session into the remote GPU."""
        host, user, port = self._resolve_connection_details(instance_id)
        cmd = f"ssh -o StrictHostKeyChecking=no"
        if self.ssh_key:
            cmd += f" -i {self.ssh_key}"
        if port != 22:
            cmd += f" -p {port}"
        cmd += f" {user}@{host}"
        os.system(cmd)
