"""Local background daemon server and client for persistent vspagent agent harness."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

from vspagent import __version__
from vspagent.colab.client import internal_colab_client
from vspagent.colab.profiles import list_chrome_accounts

DAEMON_DIR = Path.home() / ".vspagent"
DAEMON_STATE_FILE = DAEMON_DIR / "daemon.json"
DAEMON_LOG_FILE = DAEMON_DIR / "daemon.log"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("VSPAGENT_PORT", "4096"))


class VspAgentDaemonHandler(BaseHTTPRequestHandler):
    server_version = f"vspagent/{__version__}"

    def log_message(self, format: str, *args: Any):
        # Redirect request logs to daemon log file / stderr
        sys.stderr.write(f"[daemon] {self.address_string()} - {format % args}\n")
        sys.stderr.flush()

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "version": __version__,
                    "pid": os.getpid(),
                    "status": internal_colab_client.status,
                    "connected": internal_colab_client.status == "connected",
                    "gpu_info": internal_colab_client.gpu_info,
                },
            )
            return

        if path == "/colab/accounts":
            accounts_data = list_chrome_accounts()
            self._send_json(200, accounts_data)
            return

        if path == "/colab/status":
            # If server has never started or process died, start it asynchronously
            if not internal_colab_client.proc or internal_colab_client.proc.returncode is not None:
                try:
                    internal_colab_client.run_sync(internal_colab_client.start(), timeout=30.0)
                except Exception as e:
                    self._send_json(
                        500,
                        {
                            "status": "error",
                            "message": f"Failed to initialize colab client: {e}",
                            "error": str(e),
                        },
                    )
                    return

            self._send_json(
                200,
                {
                    "status": internal_colab_client.status,
                    "message": internal_colab_client.status_message,
                    "gpu_info": internal_colab_client.gpu_info,
                    "selected_profile": internal_colab_client.selected_profile,
                    "profileDirectory": internal_colab_client.selected_profile,
                    "tools": list(internal_colab_client.tools.keys()),
                    "connected": internal_colab_client.status == "connected",
                    "colabAvailable": internal_colab_client.status == "connected",
                    "recent_logs": list(internal_colab_client.logs)[-25:],
                    "daemon_pid": os.getpid(),
                },
            )
            return

        self._send_json(404, {"error": f"Endpoint not found: {self.path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        data = self._read_json()

        if path == "/daemon/shutdown":
            self._send_json(200, {"ok": True, "message": "Daemon shutting down..."})

            def _shutdown():
                time.sleep(0.5)
                try:
                    internal_colab_client.run_sync(internal_colab_client.disconnect(), timeout=5.0)
                except Exception:
                    pass
                if DAEMON_STATE_FILE.exists():
                    try:
                        DAEMON_STATE_FILE.unlink()
                    except Exception:
                        pass
                os._exit(0)

            import threading
            threading.Thread(target=_shutdown, daemon=True).start()
            return

        if path == "/colab/connect":
            profile = data.get("profileDirectory") or "Default"
            force = bool(data.get("force", False))
            timeout = float(data.get("timeout", 90.0))

            async def _connect_flow():
                if internal_colab_client.status == "disconnected" or not internal_colab_client.proc:
                    await internal_colab_client.start(force_restart=force)

                await internal_colab_client.connect_browser(profile_directory=profile, force=force)
                deadline = time.time() + timeout
                while time.time() < deadline:
                    if internal_colab_client.status == "connected":
                        break
                    await asyncio.sleep(1.0)

                # Wait briefly for GPU hardware probe if connected
                if internal_colab_client.status == "connected" and not internal_colab_client.gpu_info:
                    probe_deadline = time.time() + 8.0
                    while time.time() < probe_deadline and not internal_colab_client.gpu_info:
                        await asyncio.sleep(0.5)

                return {
                    "status": internal_colab_client.status,
                    "connected": internal_colab_client.status == "connected",
                    "message": internal_colab_client.status_message,
                    "gpu_info": internal_colab_client.gpu_info,
                    "selected_profile": internal_colab_client.selected_profile,
                    "tools": list(internal_colab_client.tools.keys()),
                }

            try:
                result = internal_colab_client.run_sync(_connect_flow(), timeout=timeout + 15.0)
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e), "error": str(e)})
            return

        if path == "/colab/execute":
            code = data.get("code")
            if not code:
                self._send_json(400, {"status": "error", "message": "Missing 'code' field"})
                return

            keep_cell = bool(data.get("keep_cell", True))
            timeout = float(data.get("timeout", 3600.0))

            if internal_colab_client.status != "connected":
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "message": "Colab GPU runtime is not connected. Call 'vspagent colab connect' first.",
                    },
                )
                return

            try:
                res = internal_colab_client.run_sync(
                    internal_colab_client.execute_code(code=code, keep_cell=keep_cell, timeout=timeout),
                    timeout=timeout + 10.0,
                )
                self._send_json(200, res)
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e), "error": str(e)})
            return

        if path == "/colab/disconnect":
            try:
                internal_colab_client.run_sync(internal_colab_client.disconnect(), timeout=10.0)
                self._send_json(200, {"status": "disconnected", "message": "Colab session disconnected"})
            except Exception as e:
                self._send_json(500, {"status": "error", "message": str(e)})
            return

        self._send_json(404, {"error": f"Endpoint not found: {self.path}"})


def run_daemon_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Runs the daemon HTTP server synchronously in the foreground."""
    DAEMON_DIR.mkdir(parents=True, exist_ok=True)

    # Save state
    state = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "base_url": f"http://{host}:{port}",
        "version": __version__,
        "started_at": time.time(),
    }
    DAEMON_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    server = ThreadingHTTPServer((host, port), VspAgentDaemonHandler)
    print(f"[*] vspagent daemon listening on http://{host}:{port} (PID: {os.getpid()})")
    sys.stdout.flush()

    def _signal_handler(signum, frame):
        print(f"\n[*] Received signal {signum}, stopping daemon...")
        try:
            internal_colab_client.run_sync(internal_colab_client.disconnect(), timeout=3.0)
        except Exception:
            pass
        if DAEMON_STATE_FILE.exists():
            try:
                DAEMON_STATE_FILE.unlink()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if DAEMON_STATE_FILE.exists():
            try:
                DAEMON_STATE_FILE.unlink()
            except Exception:
                pass


def get_daemon_info() -> Optional[Dict[str, Any]]:
    """Checks if daemon state file exists and daemon process is alive."""
    if not DAEMON_STATE_FILE.is_file():
        return None
    try:
        data = json.loads(DAEMON_STATE_FILE.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if not pid:
            return None
        # Check if process is running
        try:
            os.kill(pid, 0)
        except OSError:
            # Stale PID
            DAEMON_STATE_FILE.unlink(missing_ok=True)
            return None
        return data
    except Exception:
        return None


def is_daemon_running() -> bool:
    info = get_daemon_info()
    if not info:
        return False
    base_url = info.get("base_url")
    if not base_url:
        return False
    try:
        req = urllib.request.Request(f"{base_url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_daemon_running(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """Ensures background daemon is running; starts it if not running."""
    if is_daemon_running():
        return get_daemon_info() or {"base_url": f"http://{host}:{port}"}

    DAEMON_DIR.mkdir(parents=True, exist_ok=True)
    log_fd = open(DAEMON_LOG_FILE, "a", encoding="utf-8")

    cmd = [sys.executable, "-m", "vspagent.daemon", "--host", host, "--port", str(port)]
    proc = subprocess.Popen(
        cmd,
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Poll /health until server answers
    deadline = time.time() + 8.0
    base_url = f"http://{host}:{port}"
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    info = get_daemon_info()
                    return info or {"base_url": base_url, "pid": proc.pid}
        except Exception:
            pass
        time.sleep(0.2)

    raise RuntimeError(
        f"Failed to start vspagent daemon on {base_url}. Check logs: {DAEMON_LOG_FILE}"
    )


def daemon_request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 120.0,
    auto_start: bool = True,
) -> Dict[str, Any]:
    """Sends HTTP request to running vspagent background daemon."""
    info = ensure_daemon_running() if auto_start else get_daemon_info()
    if not info or not info.get("base_url"):
        raise RuntimeError("vspagent daemon is not running.")

    base_url = info["base_url"].rstrip("/")
    url = f"{base_url}{path}"

    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            err_data = json.loads(raw)
            raise RuntimeError(err_data.get("message") or err_data.get("error") or raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {raw}")
    except Exception as e:
        raise RuntimeError(f"Daemon request failed ({url}): {e}")


def stop_daemon() -> bool:
    """Stops the running daemon process."""
    info = get_daemon_info()
    if not info:
        return False

    base_url = info.get("base_url")
    pid = info.get("pid")

    # Try clean shutdown via HTTP
    if base_url:
        try:
            req = urllib.request.Request(f"{base_url}/daemon/shutdown", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                pass
            time.sleep(0.5)
        except Exception:
            pass

    # Ensure PID is dead
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except OSError:
            pass

    if DAEMON_STATE_FILE.exists():
        try:
            DAEMON_STATE_FILE.unlink()
        except Exception:
            pass
    return True


def main():
    parser = argparse.ArgumentParser(description="vspagent Background Daemon Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 4096)")
    parser.add_argument("--stop", action="store_true", help="Stop running daemon")
    parser.add_argument("--status", action="store_true", help="Check daemon status")

    args = parser.parse_args()

    if args.stop:
        if stop_daemon():
            print("[+] Daemon stopped.")
        else:
            print("[-] Daemon is not running.")
        return

    if args.status:
        if is_daemon_running():
            info = get_daemon_info()
            print(f"[+] Daemon is running: {json.dumps(info, indent=2)}")
        else:
            print("[-] Daemon is not running.")
        return

    run_daemon_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
