"""JarvisLabs Cloud GPU Client & Agent Harness."""

from __future__ import annotations

import json
import os
import re
import shlex
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

# Bump when a breaking change lands in this module so consumers can fail fast
# instead of discovering it mid-run (e.g. a missing kwarg after provisioning).
CLIENT_API_VERSION = 3

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None


def _jl_cli_config_paths() -> List[Path]:
    """Config locations used by the official `jl` CLI (platformdirs XDG)."""
    paths = [Path.home() / ".config" / "jl" / "config.toml"]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        paths.insert(0, Path(xdg) / "jl" / "config.toml")
    return paths


def _token_from_jl_cli_config() -> Optional[str]:
    """Read the token written by `jl setup`.

    The `jl` CLI stores it in ~/.config/jl/config.toml (XDG), not in the legacy
    ~/.jarvislabs/config.json that older vspagent builds looked at. Missing this
    path is why a machine could be fully logged in to `jl` while vspagent
    insisted no token existed.
    """
    if _toml is None:
        return None
    for path in _jl_cli_config_paths():
        if not path.is_file():
            continue
        try:
            data = _toml.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # `jl setup` writes [auth] token = "..." (top-level is accepted too, in
        # case the layout changes).
        candidates = [data.get("token")]
        auth = data.get("auth")
        if isinstance(auth, dict):
            candidates.append(auth.get("token"))
            candidates.append(auth.get("api_key"))
        for token in candidates:
            if isinstance(token, str) and token.strip():
                return token.strip()
    return None


def find_token() -> Tuple[Optional[str], str]:
    """Locate the JarvisLabs API token and report *where* it came from.

    Returns ``(token, source)`` where source is a short human label such as
    ``env:JL_API_KEY``, ``file:/path/.env`` or ``jl-cli:/home/u/.config/jl/config.toml``.
    The source label exists so `vspagent jarvis doctor` can explain a
    "no token" failure instead of just asserting one.
    """
    # 1. Environment variables
    for key in ("JARVIS_LABS_API_TOKEN", "JL_API_KEY", "JARVISLABS_API_KEY", "JARVISLABS_TOKEN"):
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip(), f"env:{key}"

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
                            return v, f"file:{p}"
            except Exception:
                pass

    # 3. Dedicated credentials file
    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
            if data.get("token"):
                return data["token"], f"file:{CREDENTIALS_FILE}"
        except Exception:
            pass

    # 4. ~/.jarvislabs/config.json if user used the older official CLI setup
    jl_config = Path.home() / ".jarvislabs" / "config.json"
    if jl_config.exists():
        try:
            data = json.loads(jl_config.read_text(encoding="utf-8"))
            token = data.get("jwt") or data.get("token") or data.get("api_key")
            if token:
                return token, f"file:{jl_config}"
        except Exception:
            pass

    # 5. Current `jl` CLI store (~/.config/jl/config.toml). Without this a host
    #    can be fully authenticated for `jl` while vspagent reports no token.
    token = _token_from_jl_cli_config()
    if token:
        for path in _jl_cli_config_paths():
            if path.is_file():
                return token, f"jl-cli:{path}"

    return None, "none"


def _find_env_token() -> Optional[str]:
    """Search environment, .env files, and local config for JarvisLabs API token."""
    return find_token()[0]


def _find_default_ssh_key() -> Optional[str]:
    """Auto-detect available local SSH private key."""
    home_ssh = Path.home() / ".ssh"
    for candidate in ("id_ed25519_jarvis", "id_ed25519", "id_rsa", "id_ecdsa"):
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
        password: str = "",
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
            "password": password,
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
        """Retrieve the primary/active instance configuration, pruning any cached instance
        that has been deleted on JarvisLabs."""
        remote = self.list_instances()
        for inst in remote:
            if str(inst.get("status", "")).lower() == "running" and inst.get("host"):
                return inst

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
        """List all instances from the official SDK or JarvisLabs REST API and prune stale local entries."""
        results = []
        seen_ids = set()
        remote_verified = False

        # 1. Query official SDK if installed and configured
        if self._sdk_client:
            try:
                remote_list = self._sdk_client.instances.list()
                remote_verified = True
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
                        "password": getattr(inst, "password", ""),
                        "ssh_command": ssh_cmd or f"ssh {user}@{host}",
                    }
                    results.append(item)
                    seen_ids.add(mid)
            except Exception:
                pass
        elif self.token:
            try:
                import requests

                resp = requests.get(
                    "https://backendn.jarvislabs.net/users/fetch",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=15,
                )
                if resp.ok:
                    remote_verified = True
                    for raw in resp.json().get("instances", []) or []:
                        if isinstance(raw, dict):
                            mid = str(raw.get("machine_id") or raw.get("id") or "")
                            host = str(raw.get("public_ip") or raw.get("ip") or raw.get("host") or "")
                            ssh_cmd = str(raw.get("ssh_str") or raw.get("ssh_command") or "")
                            item = {
                                "machine_id": mid,
                                "name": raw.get("instance_name") or raw.get("name") or "remote-gpu",
                                "host": host,
                                "user": "root",
                                "port": 22,
                                "gpu_type": raw.get("gpu_type") or "GPU",
                                "status": raw.get("status") or "Unknown",
                                "jupyter_url": raw.get("url") or raw.get("jupyter_url"),
                                "ssh_command": ssh_cmd or (f"ssh root@{host}" if host else ""),
                            }
                            results.append(item)
                            seen_ids.add(mid)
            except Exception:
                pass

        # 2. Reconcile locally registered instances (auto-prune deleted JarvisLabs machine_ids)
        saved = self._load_saved_instances()
        dirty = False
        for k in list(saved.keys()):
            if k == "active_id":
                continue
            v = saved.get(k)
            if not isinstance(v, dict):
                continue
            if k not in seen_ids:
                if remote_verified and not str(k).startswith("inst-"):
                    saved.pop(k, None)
                    if saved.get("active_id") == k:
                        saved.pop("active_id", None)
                    dirty = True
                else:
                    results.append(v)
        if dirty:
            self._save_saved_instances(saved)

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
            storage=hdd,
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
            password=getattr(inst, "password", ""),
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

    def exec_jupyter(
        self,
        command: str,
        instance_id: Optional[str] = None,
        stream: bool = True,
    ) -> Tuple[int, str]:
        """Execute a bash command on the GPU instance via the Jupyter HTTPS/WebSocket interface (Port 443)."""
        import requests
        import uuid
        import websocket

        inst = self.get_active_instance() if not instance_id else self._load_saved_instances().get(str(instance_id))
        if not inst:
            raise ValueError("No active or specified instance found.")

        # get_active_instance() comes from the SDK/API list, which does not
        # include the Jupyter password. Merge in the locally saved record for the
        # same machine_id, otherwise every HTTPS-transport call fails with
        # "Jupyter URL or password not available" even though we stored them at
        # registration time.
        saved = self._load_saved_instances().get(str(inst.get("machine_id", "")))
        if saved:
            merged = dict(saved)
            merged.update({k: v for k, v in inst.items() if v})
            inst = merged

        jupyter_url = inst.get("jupyter_url", "")
        password = inst.get("password", "")
        if not jupyter_url or not password:
            raise ValueError(
                "Jupyter URL or password not available for this instance. "
                "Re-register it with `vspagent jarvis adopt <IP> --jupyter-url <url> --password <pw>`, "
                "or use --transport ssh."
            )

        base_url = jupyter_url.rstrip("/").replace("/lab", "")
        session = requests.Session()
        session.get(f"{base_url}/login")
        xsrf = session.cookies.get("_xsrf", "")
        session.post(f"{base_url}/login", data={"password": password, "_xsrf": xsrf}, headers={"Referer": f"{base_url}/login"})
        xsrf = session.cookies.get("_xsrf", "")

        headers = {"X-XSRFToken": xsrf, "Content-Type": "application/json"}
        r = session.post(f"{base_url}/api/kernels", headers=headers, json={"name": "python3"})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Failed to start Jupyter kernel: {r.text}")
        kernel_id = r.json()["id"]

        cookie_str = "; ".join([f"{c.name}={c.value}" for c in session.cookies])
        ws_protocol = "wss" if base_url.startswith("https") else "ws"
        host_domain = base_url.split("://")[-1]
        ws_url = f"{ws_protocol}://{host_domain}/api/kernels/{kernel_id}/channels"
        ws = websocket.create_connection(ws_url, header={"Cookie": cookie_str})

        marker = "__VSP_EXIT__:"
        # Run through a real subprocess rather than IPython's `!cmd` shell
        # escape. `!` always replies status="ok", so failing commands looked like
        # successes (a `test -d` on a missing dir returned 0), and anything
        # backgrounded died with the kernel's process group.
        code = (
            "import subprocess as _vsp_s, sys as _vsp_sys\n"
            f"_vsp_cmd = {json.dumps(command)}\n"
            "_vsp_r = _vsp_s.run(['bash', '-lc', _vsp_cmd], capture_output=True, text=True)\n"
            "_vsp_sys.stdout.write(_vsp_r.stdout)\n"
            "_vsp_sys.stdout.write(_vsp_r.stderr)\n"
            f"_vsp_sys.stdout.write('{marker}%d\\n' % _vsp_r.returncode)\n"
        )
        msg_id = str(uuid.uuid4())
        execute_msg = {
            "header": {"msg_id": msg_id, "username": "vsp", "session": str(uuid.uuid4()), "msg_type": "execute_request", "version": "5.3"},
            "parent_header": {}, "metadata": {},
            "content": {"code": code, "silent": False, "store_history": True, "user_expressions": {}, "allow_stdin": False},
            "channel": "shell"
        }
        ws.send(json.dumps(execute_msg))
        out_chunks = []
        kernel_ok = True
        # Streaming filter: hold back a small tail so the internal exit marker is
        # never echoed to the user, even when the transport splits it across
        # chunks ("__VSP_EXIT__:" arriving as "__VSP_" + "EXIT__:0").
        holdback = ""

        try:
            while True:
                data = json.loads(ws.recv())
                msg_type = data.get("msg_type")
                content = data.get("content", {})
                if msg_type == "stream":
                    text = content.get("text", "")
                    out_chunks.append(text)
                    if stream:
                        holdback += text
                        keep = len(marker) + 32
                        if len(holdback) > keep:
                            sys.stdout.write(holdback[:-keep])
                            sys.stdout.flush()
                            holdback = holdback[-keep:]
                elif msg_type == "error":
                    kernel_ok = False
                    err_text = "\n".join(content.get("traceback", []))
                    if stream:
                        sys.stderr.write(err_text + "\n")
                    out_chunks.append(err_text)
                elif msg_type == "execute_reply":
                    if content.get("status") != "ok":
                        kernel_ok = False
                    break
        finally:
            ws.close()
            session.delete(f"{base_url}/api/kernels/{kernel_id}", headers=headers)

        text = "".join(out_chunks)
        if stream and holdback:
            cut = holdback.find(marker)
            visible = holdback[:cut] if cut >= 0 else holdback
            if visible:
                sys.stdout.write(visible)
                sys.stdout.flush()
        exit_code = 0
        if marker in text:
            head, _, tail = text.rpartition(marker)
            text = head
            try:
                exit_code = int(tail.strip().splitlines()[0])
            except (ValueError, IndexError):
                exit_code = 1
        elif not kernel_ok:
            exit_code = 1

        return exit_code, text

    def spawn(
        self,
        command: str,
        log_path: str = "/tmp/vsp_spawn.log",
        instance_id: Optional[str] = None,
        workdir: str = "/home",
    ) -> Tuple[int, str]:
        """Start a long-lived background process that survives session teardown.

        Always use this instead of appending ``&`` yourself. A bare ``nohup cmd &``
        dies when the Jupyter kernel (or SSH session) is torn down because it
        shares the process group; ``setsid`` puts it in a new session so it
        survives. All three streams are redirected so the parent never blocks
        waiting for a pipe to close.
        """
        # `cd dir; cmd &` — NOT `cd dir && cmd &`. With `&&`, bash backgrounds the
        # whole AND-list and then blocks waiting for it, so the call hangs until
        # the spawned process exits. A `;` separator backgrounds only the command.
        inner = (
            f"cd {shlex.quote(workdir)}; "
            f"setsid nohup {command} > {shlex.quote(log_path)} 2>&1 < /dev/null &"
        )
        return self.exec(inner, instance_id=instance_id, workdir=workdir)

    def spawn_jupyter(
        self,
        command: str,
        log_path: str = "/tmp/vsp_spawn.log",
        instance_id: Optional[str] = None,
        workdir: str = "/home",
    ) -> Tuple[int, str]:
        """Same as :meth:`spawn` but forced over the Jupyter HTTPS transport."""
        inner = (
            f"cd {shlex.quote(workdir)}; "
            f"setsid nohup {command} > {shlex.quote(log_path)} 2>&1 < /dev/null &"
        )
        return self.exec_jupyter(inner, instance_id=instance_id, stream=False)

    def file_size(self, path: str, deref: bool = True, instance_id: Optional[str] = None) -> int:
        """Remote file size in bytes, or 0 when missing.

        ``deref=True`` (the default) follows symlinks, which matters because
        JarvisLabs templates ship many models as symlinks into a read-only Ceph
        mount (``/home/.sd``). Plain ``stat`` reports the *link* length (~37
        bytes) for those, so callers conclude a 250 MB model is missing, try to
        re-download it, and wget then follows the symlink into the read-only
        mount and fails with "Read-only file system".
        """
        flag = "-Lc" if deref else "-c"
        code, out = self.exec(
            f"stat {flag} %s {shlex.quote(path)} 2>/dev/null || true",
            instance_id=instance_id,
            stream=False,
        )
        try:
            return int(out.strip().splitlines()[-1] or "0")
        except (ValueError, IndexError):
            return 0

    def wait_for_port(
        self,
        port: int,
        timeout: int = 600,
        interval: int = 5,
        instance_id: Optional[str] = None,
        host: str = "127.0.0.1",
    ) -> bool:
        """Block until a TCP port accepts connections on the remote host."""
        deadline = time.time() + timeout
        probe = f"timeout 3 bash -c '</dev/tcp/{host}/{port}' 2>/dev/null && echo open || echo closed"
        while time.time() < deadline:
            code, out = self.exec(probe, instance_id=instance_id, stream=False)
            if "open" in out:
                return True
            time.sleep(interval)
        return False

    def wait_for_http(
        self,
        port: int,
        path: str = "/",
        timeout: int = 600,
        interval: int = 5,
        instance_id: Optional[str] = None,
        host: str = "127.0.0.1",
        accept: Tuple[str, ...] = ("200", "204", "301", "302"),
    ) -> bool:
        """Block until an HTTP endpoint answers with an acceptable status code.

        Matches on substring, not ``str.endswith``: SSH puts host-key warnings on
        stderr and they can land *after* the status code, which silently turned a
        healthy 200 into a "not ready" verdict.
        """
        deadline = time.time() + timeout
        url = f"http://{host}:{port}{path}"
        probe = f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {shlex.quote(url)} || true"
        while time.time() < deadline:
            code, out = self.exec(probe, instance_id=instance_id, stream=False)
            if any(str(s) in out for s in accept):
                return True
            time.sleep(interval)
        return False

    def kill_port(self, port: int, instance_id: Optional[str] = None, wait: int = 3) -> Tuple[int, str]:
        """Kill whatever process is listening on ``port``, without external tools.

        JarvisLabs templates often have **no** ``ss``, ``lsof`` or ``fuser``
        installed, so the usual one-liners silently match nothing and the old
        server keeps the port, making the restart look like a no-op. This reads
        ``/proc/net/tcp{,6}`` for the LISTEN socket inode and scans ``/proc/*/fd``
        for the owning PID, which needs only Python.
        """
        script = r'''
import os, sys, signal, time
port = int(sys.argv[1])
hexport = "%04X" % port
inodes = set()
for path in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        lines = open(path).read().splitlines()[1:]
    except OSError:
        continue
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        local, state, inode = parts[1], parts[3], parts[9]
        if state != "0A":
            continue
        if local.rsplit(":", 1)[-1].upper() != hexport:
            continue
        inodes.add(inode)
if not inodes:
    print("no listener on port %d" % port)
    sys.exit(0)
targets = {"socket:[%s]" % i for i in inodes}
killed = []
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        fds = os.listdir("/proc/%s/fd" % pid)
    except OSError:
        continue
    for fd in fds:
        try:
            link = os.readlink("/proc/%s/fd/%s" % (pid, fd))
        except OSError:
            continue
        if link in targets:
            try:
                os.kill(int(pid), signal.SIGKILL)
                killed.append(pid)
            except OSError:
                pass
            break
print("killed %s on port %d" % (",".join(killed) or "nothing", port))
'''
        quoted = shlex.quote(script)
        code, out = self.exec(
            f"python3 -c {quoted} {port}", instance_id=instance_id, stream=False,
        )
        # Belt-and-braces: also drop a server started as `python main.py --port N`.
        self.exec(
            f"pkill -f 'python main[.]py --port {port}' 2>/dev/null || true; sleep {wait}",
            instance_id=instance_id, stream=False,
        )
        return code, out

    def restart_service(
        self,
        start_cmd: str,
        port: int,
        ready_path: str = "/",
        timeout: int = 600,
        workdir: str = "/home",
        log_path: str = "/tmp/vsp_service.log",
        instance_id: Optional[int] = None,
    ) -> bool:
        """Restart a port-based service safely, then wait for it to answer.

        Three traps this avoids:

        1. Killing by command-line pattern is fragile. A service started as
           ``cd dir && python main.py`` has the cmdline ``python main.py``, so a
           pattern like ``ComfyUI/main.py`` never matches it.
        2. Killing and starting in one shell line is self-destructive: the start
           half contains the same text, so ``pkill -f`` matches the shell running
           the command and kills itself before the service launches.
        3. Templates may not ship ``ss``/``lsof``/``fuser`` at all.

        So: kill by port in its own call, then spawn in a second call.
        """
        self.kill_port(port, instance_id=instance_id)
        self.spawn(start_cmd, log_path=log_path, instance_id=instance_id, workdir=workdir)
        ok = self.wait_for_http(port, ready_path, timeout=timeout, instance_id=instance_id)
        if not ok:
            code, tail = self.exec(f"tail -40 {shlex.quote(log_path)}", instance_id=instance_id, stream=False)
            raise RuntimeError(f"Service on port {port} did not become ready in {timeout}s:\n{tail[-3000:]}")
        return True

    def instance(
        self,
        gpu_type: str = "A100",
        template: str = "comfyui",
        storage: int = 100,
        region: str = "IN2",
        name: str = "vsp-agent",
        destroy_on_exit: bool = True,
        fs_id: Optional[int] = None,
    ):
        """Context manager that guarantees the GPU is destroyed on exit.

        ``finally`` blocks do not run on SIGINT/SIGTERM, and a SIGKILL skips them
        entirely, which leaves a GPU billing by the hour. This registers an
        ``atexit`` hook plus signal handlers so cleanup happens on Ctrl-C too.
        """
        import atexit
        import contextlib
        import signal

        if not self._sdk_client:
            raise RuntimeError("jarvislabs SDK is not available; cannot create instances.")

        created = self._sdk_client.instances.create(
            gpu_type=gpu_type,
            name=name,
            template=template,
            storage=storage,
            region=region,
            fs_id=fs_id,
        )
        machine_id = int(created.machine_id)
        destroyed = {"done": False}

        def _cleanup(*_args):
            if destroyed["done"] or not destroy_on_exit:
                return
            destroyed["done"] = True
            try:
                self._sdk_client.instances.destroy(machine_id)
                print(f"[vspagent] destroyed instance {machine_id}", file=sys.stderr)
            except Exception as exc:  # pragma: no cover
                print(f"[vspagent] WARNING: could not destroy {machine_id}: {exc}", file=sys.stderr)

        atexit.register(_cleanup)
        previous = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[sig] = signal.getsignal(sig)
                signal.signal(sig, lambda s, f: (_cleanup(), sys.exit(130)))
            except (ValueError, OSError):  # not main thread
                pass

        @contextlib.contextmanager
        def _ctx():
            try:
                yield machine_id
            finally:
                _cleanup()
                atexit.unregister(_cleanup)
                for sig, handler in previous.items():
                    try:
                        signal.signal(sig, handler)
                    except (ValueError, OSError):
                        pass

        return _ctx()

    def upload_jupyter(
        self,
        local_path: str,
        remote_filename: Optional[str] = None,
        instance_id: Optional[str] = None,
    ) -> bool:
        """Upload a file to the GPU instance root directory via Jupyter REST API (Port 443)."""
        import requests
        inst = self.get_active_instance() if not instance_id else self._load_saved_instances().get(str(instance_id))
        if not inst:
            raise ValueError("No active or specified instance found.")

        jupyter_url = inst.get("jupyter_url", "")
        password = inst.get("password", "")
        if not jupyter_url or not password:
            raise ValueError("Jupyter URL or password not available.")

        base_url = jupyter_url.rstrip("/").replace("/lab", "")
        session = requests.Session()
        session.get(f"{base_url}/login")
        xsrf = session.cookies.get("_xsrf", "")
        session.post(f"{base_url}/login", data={"password": password, "_xsrf": xsrf}, headers={"Referer": f"{base_url}/login"})
        xsrf = session.cookies.get("_xsrf", "")

        path = Path(local_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {local_path}")

        target_name = remote_filename or path.name
        content = path.read_text(encoding="utf-8", errors="replace")
        resp = session.put(
            f"{base_url}/api/contents/{target_name}",
            json={"content": content, "format": "text", "type": "file"},
            headers={"X-XSRFToken": xsrf}
        )
        return resp.status_code in (200, 201)

    def exec(
        self,
        command: str,
        instance_id: Optional[str] = None,
        workdir: str = "/home",
        stream: bool = True,
        env_vars: Optional[Dict[str, str]] = None,
        prefer_jupyter: bool = False,
    ) -> Tuple[int, str]:
        """Execute a remote bash command over SSH on the GPU instance with automatic Jupyter HTTPS fallback."""
        inst = self.get_active_instance() if not instance_id else self._load_saved_instances().get(str(instance_id))
        has_jupyter = inst and inst.get("jupyter_url") and inst.get("password")

        if prefer_jupyter and has_jupyter:
            return self.exec_jupyter(command, instance_id=instance_id, stream=stream)

        host, user, port = self._resolve_connection_details(instance_id)

        env_prefix = ""
        if env_vars:
            exports = [f"export {k}='{v}'" for k, v in env_vars.items()]
            env_prefix = " && ".join(exports) + " && "

        full_remote_cmd = f"{env_prefix}cd {workdir} && {command}"

        ssh_cmd = [
            "ssh",
            "-n",  # never forward local stdin: a forwarded stdin keeps the channel
                   # open, so `cmd &` looks like it hangs until the local process
                   # is killed. This is why `spawn()`/background jobs appeared to
                   # time out even with all remote streams redirected.
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=30",
        ]
        if self.ssh_key:
            ssh_cmd.extend(["-i", self.ssh_key])
        if port != 22:
            ssh_cmd.extend(["-p", str(port)])

        ssh_cmd.extend([f"{user}@{host}", full_remote_cmd])

        try:
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
                if proc.returncode == 255 and has_jupyter:
                    print("\n[vspagent] SSH connection failed/timed out. Switching to Jupyter HTTPS execution...")
                    return self.exec_jupyter(command, instance_id=instance_id, stream=stream)
                return proc.returncode, "".join(output_lines)
            else:
                res = subprocess.run(ssh_cmd, capture_output=True, text=True)
                if res.returncode == 255 and has_jupyter:
                    print("[vspagent] SSH connection failed/timed out. Switching to Jupyter HTTPS execution...")
                    return self.exec_jupyter(command, instance_id=instance_id, stream=stream)
                return res.returncode, res.stdout + res.stderr
        except Exception as e:
            if has_jupyter:
                print(f"[vspagent] SSH error ({e}). Switching to Jupyter HTTPS execution...")
                return self.exec_jupyter(command, instance_id=instance_id, stream=stream)
            raise

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
        """Upload local file or directory to remote GPU instance via SCP (with Jupyter REST fallback)."""
        inst = self.get_active_instance() if not instance_id else self._load_saved_instances().get(str(instance_id))
        has_jupyter = inst and inst.get("jupyter_url") and inst.get("password")

        host, user, port = self._resolve_connection_details(instance_id)
        local_p = Path(local_path)
        if not local_p.exists():
            raise FileNotFoundError(f"Source path does not exist: {local_path}")

        scp_cmd = [
            "scp",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=5",
        ]
        if local_p.is_dir():
            scp_cmd.append("-r")
        if self.ssh_key:
            scp_cmd.extend(["-i", self.ssh_key])
        if port != 22:
            scp_cmd.extend(["-P", str(port)])

        scp_cmd.extend([str(local_p), f"{user}@{host}:{remote_path}"])
        res = subprocess.run(scp_cmd)
        if res.returncode != 0 and has_jupyter and local_p.is_file():
            print(f"[vspagent] SCP failed (code {res.returncode}). Falling back to Jupyter REST upload...")
            return self.upload_jupyter(local_path, instance_id=instance_id)
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
