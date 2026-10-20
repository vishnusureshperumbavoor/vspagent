"""Persistent Google Colab MCP client for remote cloud GPU execution."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, AsyncGenerator, Dict, List, Optional

UVX_PATH = shutil.which("uvx") or os.path.expanduser("~/.local/bin/uvx")
SERVER_CMD = [UVX_PATH, "--refresh", "git+https://github.com/googlecolab/colab-mcp"]

# Patterns to filter out from server log stream to keep progress readable
NOISY_STDERR_PATTERNS = (
    "FastMCP", "DeprecationWarning", "│", "╭", "╯", "╰", "───",
    "FastMCP 3.0", "Update available", "logging to", "compat", "authlib",
)


def extract_text_from_result(result_obj: Any) -> str:
    """Extracts text content or raw result from an MCP tool response."""
    if not isinstance(result_obj, dict):
        return str(result_obj)

    if "structuredContent" in result_obj and isinstance(result_obj["structuredContent"], dict):
        if "result" in result_obj["structuredContent"]:
            return str(result_obj["structuredContent"]["result"])

    contents = result_obj.get("content", [])
    text_parts = []
    for c in contents:
        if isinstance(c, dict) and c.get("type") == "text":
            text_parts.append(c.get("text", ""))
    if text_parts:
        return "\n".join(text_parts).strip()

    if "result" in result_obj:
        return str(result_obj["result"])
    return json.dumps(result_obj)


def extract_cell_id(result_obj: Any) -> str:
    """Extracts clean cell ID from add_code_cell / add_text_cell response."""
    if isinstance(result_obj, dict):
        if "structuredContent" in result_obj and isinstance(result_obj["structuredContent"], dict):
            sc = result_obj["structuredContent"]
            if "newCellId" in sc:
                return str(sc["newCellId"]).strip('"\' ')
        if "result" in result_obj and isinstance(result_obj["result"], dict):
            r = result_obj["result"]
            if "newCellId" in r:
                return str(r["newCellId"]).strip('"\' ')

    text = extract_text_from_result(result_obj)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("newCellId") or data.get("cellId") or data.get("id") or text).strip('"\' ')
    except Exception:
        pass

    match = re.search(r'["\']newCellId["\']\s*:\s*["\']([^"\']+)["\']', text)
    if match:
        return match.group(1).strip()

    return text.strip('"\' \n{}')


class ColabMCPClient:
    """Persistent Google Colab MCP client supporting both async coroutines and sync callers."""

    def __init__(self):
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.status = "disconnected"  # disconnected, connecting, connected, error
        self.status_message = "Not started"
        self.gpu_info: Optional[str] = None
        self.selected_profile: Optional[str] = "Default"
        self.profile_dir: Optional[str] = "Default"
        self.authuser: Optional[int] = 0
        self.google_email: Optional[str] = None
        self.tools: Dict[str, Any] = {}
        self.logs: deque = deque(maxlen=300)

        self._lock: Optional[asyncio.Lock] = None
        self._connected_event: Optional[asyncio.Event] = None
        self._request_id = 0
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._reader_tasks: List[asyncio.Task] = []

        # Background dedicated event loop thread for synchronous integration
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._loop_ready.wait(timeout=5.0)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._lock = asyncio.Lock()
        self._connected_event = asyncio.Event()
        self._loop_ready.set()
        self._loop.run_forever()

    def run_sync(self, coro, timeout: float = 7200.0) -> Any:
        """Run an async coroutine on the background event loop from synchronous code."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def log(self, message: str):
        msg = f"[vspagent ColabMCP] {message}"
        self.logs.append(msg)

    async def start(self, force_restart: bool = False):
        """Starts the persistent colab-mcp subprocess and performs MCP handshake."""
        async with self._lock:
            if self.proc and self.proc.returncode is None and not force_restart:
                return

            if self.proc and self.proc.returncode is None and force_restart:
                try:
                    self.proc.terminate()
                    await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                except Exception:
                    pass

            self.status = "connecting"
            self.status_message = "Starting internal colab-mcp server..."
            self.log(f"Launching server: {' '.join(SERVER_CMD)}")

            try:
                from vspagent.colab.profiles import browser_env_command, set_selected_profile

                set_selected_profile(self.selected_profile or "Default")
                child_env = os.environ.copy()
                child_env["BROWSER"] = browser_env_command()

                self.proc = await asyncio.create_subprocess_exec(
                    *SERVER_CMD,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=child_env,
                    limit=32 * 1024 * 1024,
                )
            except Exception as e:
                self.status = "error"
                self.status_message = f"Failed to start colab-mcp process: {e}"
                self.log(self.status_message)
                return

            self._reader_tasks = [
                asyncio.create_task(self._read_stdout()),
                asyncio.create_task(self._read_stderr()),
            ]

            try:
                self._request_id += 1
                init_msg = {
                    "jsonrpc": "2.0",
                    "id": self._request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "roots": {"listChanged": True},
                        },
                        "clientInfo": {
                            "name": "vspagent-colab-mcp",
                            "version": "3.0.0",
                        },
                    },
                }
                self.log("Sending MCP initialize...")
                res = await self._send_request(init_msg)
                server_name = res.get("serverInfo", {}).get("name", "ColabMCP")
                self.log(f"Initialized with server: {server_name}")

                await self._send_notification("notifications/initialized", {})
                await self.refresh_tools()
                self.status_message = "Server started. Ready to pair with Colab."
                self.log("Internal colab-mcp server initialized successfully.")

            except Exception as e:
                self.status = "error"
                self.status_message = f"Handshake failed: {e}"
                self.log(self.status_message)

    async def _send_notification(self, method: str, params: Optional[Dict] = None):
        if not self.proc or not self.proc.stdin:
            return
        msg: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        data = json.dumps(msg) + "\n"
        self.proc.stdin.write(data.encode("utf-8"))
        await self.proc.stdin.drain()

    async def _send_request(self, msg: Dict[str, Any]) -> Any:
        req_id = msg["id"]
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_futures[req_id] = future

        data = json.dumps(msg) + "\n"
        self.proc.stdin.write(data.encode("utf-8"))
        await self.proc.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=3600.0)
        finally:
            self._pending_futures.pop(req_id, None)

    async def _read_stdout(self):
        if self.proc and self.proc.stdout and hasattr(self.proc.stdout, "_limit"):
            self.proc.stdout._limit = 32 * 1024 * 1024
        while self.proc and self.proc.stdout:
            try:
                line = await self.proc.stdout.readline()
            except Exception as e:
                self.log(f"[STDOUT READ ERROR] {e}")
                continue
            if not line:
                break
            line_str = line.decode(errors="replace").strip()
            if not line_str:
                continue

            try:
                msg = json.loads(line_str)
            except json.JSONDecodeError:
                self.log(f"[STDOUT] {line_str}")
                continue

            if "id" in msg and msg["id"] in self._pending_futures:
                fut = self._pending_futures[msg["id"]]
                if not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"].get("message", "MCP error")))
                    else:
                        fut.set_result(msg.get("result", {}))

            elif "method" in msg:
                method = msg["method"]
                if method == "notifications/tools/list_changed":
                    self.log("Tools changed. Refreshing...")
                    asyncio.create_task(self.refresh_tools())

    async def _read_stderr(self):
        while self.proc and self.proc.stderr:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            if text and not any(p in text for p in NOISY_STDERR_PATTERNS):
                self.log(f"[SERVER] {text}")

    async def refresh_tools(self):
        """Fetches available tools from the MCP server."""
        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
            "params": {},
        }
        res = await self._send_request(msg)
        tools_list = res.get("tools", [])
        self.tools = {t["name"]: t for t in tools_list}
        self.log(f"Active tools ({len(self.tools)}): {', '.join(self.tools.keys())}")

        if "add_code_cell" in self.tools and "run_code_cell" in self.tools:
            was_connected = self.status == "connected"
            self.status = "connected"
            self.status_message = "Connected to Google Colab GPU session!"
            if self._connected_event:
                self._connected_event.set()
            if not was_connected and not self.gpu_info:
                asyncio.create_task(self._probe_gpu_info())

    async def _probe_gpu_info(self):
        """Probes GPU hardware details on the connected runtime."""
        try:
            probe_code = (
                "import torch\n"
                "if torch.cuda.is_available():\n"
                "    props = torch.cuda.get_device_properties(0)\n"
                "    print(f'GPU_INFO:{torch.cuda.get_device_name(0)} ({props.total_memory / (1024**3):.1f} GB VRAM)')\n"
                "else:\n"
                "    print('GPU_INFO:CPU Runtime (Enable GPU in Colab: Runtime -> Change runtime type)')"
            )
            res = await self.execute_code(probe_code, keep_cell=False)
            for line in res.get("output", "").splitlines():
                if line.startswith("GPU_INFO:"):
                    self.gpu_info = line.split("GPU_INFO:", 1)[1].strip()
                    self.status_message = f"Connected: {self.gpu_info}"
                    self.log(f"Detected Colab runtime: {self.gpu_info}")
                    break
        except Exception as e:
            self.log(f"GPU probe warning: {e}")

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Invokes an MCP tool by name."""
        if not self.proc or self.proc.returncode is not None:
            await self.start()

        self._request_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        }
        return await self._send_request(msg)

    async def select_profile(
        self,
        profile_dir: Optional[str] = None,
        authuser: Optional[int] = None,
        email: Optional[str] = None,
    ) -> None:
        """Selects Chrome profile and account for the next Colab pairing session."""
        self.profile_dir = profile_dir or "Default"
        self.selected_profile = self.profile_dir
        self.authuser = authuser
        self.google_email = email
        from vspagent.colab.profiles import set_selected_profile
        try:
            set_selected_profile(self.selected_profile)
        except Exception as e:
            self.log(f"Profile select warning: {e}")

    async def connect_browser(
        self, profile_directory: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        """Triggers open_colab_browser_connection with the selected Chrome profile."""
        from vspagent.colab.profiles import set_selected_profile

        if self.status == "connected" and not force:
            return {
                "status": "already_connected",
                "connected": True,
                "gpu_info": self.gpu_info,
                "message": self.status_message,
            }

        selected = set_selected_profile(profile_directory)
        self.selected_profile = selected.get("profileDirectory") or "Default"
        self.log(f"Pairing Colab browser tab with Chrome profile: {self.selected_profile}...")
        self.status = "connecting"
        self.status_message = f"Waiting for Colab tab pairing ({self.selected_profile})..."
        res = await self.call_tool("open_colab_browser_connection", {})
        await self.refresh_tools()
        return {
            "status": "connected" if self.status == "connected" else "connecting",
            "profileDirectory": self.selected_profile,
            "connected": self.status == "connected",
            "gpu_info": self.gpu_info,
            "message": self.status_message,
            "result": res,
        }

    async def ensure_connected(self, timeout: float = 60.0):
        """Ensures that a connected Colab session exists, or waits up to timeout."""
        if self.status == "connected":
            return

        if self._connected_event:
            self._connected_event.clear()

        if self.status == "disconnected" or not self.proc:
            await self.connect_browser()

        if self.status != "connected" and self._connected_event:
            try:
                await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(f"Timed out waiting for Colab tab pairing after {timeout}s.")

    async def execute_code(
        self, code: str, keep_cell: bool = True, timeout: float = 3600.0
    ) -> Dict[str, Any]:
        """Executes Python code remotely in the connected Google Colab notebook session."""
        await self.ensure_connected()

        # Step 1: Add code cell
        add_res = await self.call_tool("add_code_cell", {"code": code})
        cell_id = extract_cell_id(add_res)

        if not cell_id:
            return {
                "status": "error",
                "error": f"Failed to retrieve cellId from add_code_cell: {add_res}",
                "raw": add_res,
            }

        # Step 2: Execute code cell
        exec_tool = "run_code_cell" if "run_code_cell" in self.tools else "execute_cell"
        exec_args = {"cellId": cell_id} if exec_tool == "run_code_cell" else {"cell_id": cell_id}

        exec_res = await asyncio.wait_for(self.call_tool(exec_tool, exec_args), timeout=timeout)
        raw_output = extract_text_from_result(exec_res)

        # Parse error state and output text
        is_error = False
        parsed_output = raw_output
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                outputs = parsed.get("outputs", [])
                lines = []
                for out in outputs:
                    if out.get("output_type") == "error":
                        is_error = True
                    for l in out.get("text", []):
                        lines.append(l)
                    for trace in out.get("traceback", []):
                        lines.append(trace)
                if lines:
                    parsed_output = "".join(lines)
        except Exception:
            pass

        # Step 3: Cleanup if keep_cell is False
        if not keep_cell:
            try:
                del_tool = "delete_cell" if "delete_cell" in self.tools else "remove_cell"
                await self.call_tool(del_tool, {"cellId": cell_id} if del_tool == "delete_cell" else {"cell_id": cell_id})
            except Exception as e:
                self.log(f"Warning: could not delete cell {cell_id}: {e}")

        return {
            "status": "error" if is_error else "success",
            "cellId": cell_id,
            "output": parsed_output,
            "rawOutput": raw_output,
            "isError": is_error,
        }

    async def upload_file_to_colab(self, local_path: str, remote_path: str):
        """Transfers a local binary file to Google Colab via chunked base64 cells."""
        with open(local_path, "rb") as f:
            raw_bytes = f.read()
        b64_data = base64.b64encode(raw_bytes).decode("ascii")
        chunk_size = 700_000  # ~700 KB per chunk
        chunks = [b64_data[i : i + chunk_size] for i in range(0, len(b64_data), chunk_size)]
        self.log(f"Uploading {os.path.basename(local_path)} ({len(raw_bytes)/1024:.1f} KB) to Colab {remote_path} in {len(chunks)} chunk(s)...")

        tmp_b64 = f"{remote_path}.b64"
        remote_dir = os.path.dirname(remote_path) or "/content"
        for idx, chunk in enumerate(chunks):
            mode = "w" if idx == 0 else "a"
            is_last = idx == len(chunks) - 1
            code = (
                "import base64, os\n"
                f"os.makedirs({remote_dir!r}, exist_ok=True)\n"
                f"with open({tmp_b64!r}, {mode!r}) as f:\n"
                f"    f.write({chunk!r})\n"
            )
            if is_last:
                code += (
                    f"with open({tmp_b64!r}, 'r') as f_in, open({remote_path!r}, 'wb') as f_out:\n"
                    "    f_out.write(base64.b64decode(f_in.read()))\n"
                    f"os.remove({tmp_b64!r})\n"
                    f"print('UPLOAD_OK:', os.path.getsize({remote_path!r}))\n"
                )
            res = await self.execute_code(code, keep_cell=False)
            if res.get("isError") or (is_last and "UPLOAD_OK:" not in res.get("output", "")):
                raise RuntimeError(f"Failed uploading {local_path} (chunk {idx+1}/{len(chunks)}) to Colab: {res.get('output')}")

    async def download_file_from_colab(self, remote_path: str, local_path: str):
        """Downloads a binary file from Google Colab to local_path via chunked base64 slices."""
        tmp_b64 = f"{remote_path}.b64"
        prep_code = (
            "import base64, os\n"
            f"if not os.path.exists({remote_path!r}):\n"
            f"    raise FileNotFoundError({remote_path!r})\n"
            f"with open({remote_path!r}, 'rb') as f:\n"
            "    b64 = base64.b64encode(f.read()).decode('ascii')\n"
            f"with open({tmp_b64!r}, 'w') as f:\n"
            "    f.write(b64)\n"
            "print(f'B64_LEN:{len(b64)}')\n"
        )
        res = await self.execute_code(prep_code, keep_cell=False)
        out = res.get("output", "")
        match = re.search(r"B64_LEN:(\d+)", out)
        if not match:
            raise RuntimeError(f"Failed preparing download for {remote_path}: {out}")
        total_len = int(match.group(1))
        chunk_size = 150_000
        parts: List[str] = []
        self.log(f"Downloading {remote_path} ({total_len * 3 // 4 // 1024} KB) from Colab...")

        for offset in range(0, total_len, chunk_size):
            slice_code = (
                f"with open({tmp_b64!r}, 'r') as f:\n"
                f"    f.seek({offset})\n"
                f"    data = f.read({chunk_size})\n"
                "print('===B64_START===' + data + '===B64_END===')\n"
            )
            slice_res = await self.execute_code(slice_code, keep_cell=False)
            slice_out = slice_res.get("output", "")
            m = re.search(r"===B64_START===(.*?)===B64_END===", slice_out, re.S)
            if not m:
                raise RuntimeError(f"Failed reading slice at {offset} from Colab: {slice_out[:300]}")
            parts.append(m.group(1).strip())

        await self.execute_code(f"import os\nif os.path.exists({tmp_b64!r}): os.remove({tmp_b64!r})", keep_cell=False)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(base64.b64decode("".join(parts)))

    async def disconnect(self):
        """Terminates the colab-mcp process."""
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3.0)
            except Exception:
                self.proc.kill()
        self.proc = None
        self.status = "disconnected"
        self.status_message = "Disconnected"
        self.gpu_info = None
        for task in self._reader_tasks:
            task.cancel()
        self._reader_tasks.clear()

    stop = disconnect

    @property
    def is_connected(self) -> bool:
        return self.status == "connected"


# Global singleton instance
internal_colab_client = ColabMCPClient()

# Alias for clean user imports
ColabClient = ColabMCPClient
