"""Command Line Interface for vspagent: Google Colab MCP Agent Harness."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

from vspagent import __version__
from vspagent.colab.profiles import list_chrome_accounts
from vspagent.jarvis import (
    JarvisLabsClient,
    list_active_tunnels,
    start_ssh_tunnel,
    stop_ssh_tunnel,
)
from vspagent.daemon import (
    DAEMON_LOG_FILE,
    daemon_request,
    ensure_daemon_running,
    get_daemon_info,
    is_daemon_running,
    run_daemon_server,
    stop_daemon,
)


def _print_info(msg: str):
    if HAS_RICH:
        console.print(f"[bold cyan]ℹ[/bold cyan] {msg}")
    else:
        print(f"[*] {msg}")


def _print_success(msg: str):
    if HAS_RICH:
        console.print(f"[bold green]✔[/bold green] {msg}")
    else:
        print(f"[+] {msg}")


def _print_error(msg: str):
    if HAS_RICH:
        console.print(f"[bold red]✖ Error:[/bold red] {msg}")
    else:
        print(f"[-] Error: {msg}")


def cmd_accounts(args):
    """List discovered Chrome profiles and signed-in Google accounts."""
    data = list_chrome_accounts()
    accounts = data.get("accounts", [])
    user_data = data.get("chromeUserDataDir")
    chrome_exe = data.get("chromeExecutable")

    if not accounts:
        _print_error("No Chrome profiles or accounts found.")
        if data.get("error"):
            print(f"Details: {data.get('error')}")
        return

    if HAS_RICH:
        table = Table(title="Discovered Chrome Accounts (Google Colab Ready)", show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Profile Directory", style="cyan")
        table.add_column("Google Email", style="green")
        table.add_column("Name", style="magenta")
        table.add_column("Default", justify="center")

        for idx, acc in enumerate(accounts, start=1):
            table.add_row(
                str(idx),
                acc["profileDirectory"],
                acc["email"] or "—",
                acc["name"] or "—",
                "★" if acc["isDefault"] else "",
            )
        console.print(table)
        console.print(f"[dim]User Data: {user_data}[/dim]")
        console.print(f"[dim]Executable: {chrome_exe}[/dim]\n")
    else:
        print("\nAvailable Chrome Accounts:")
        for idx, acc in enumerate(accounts, start=1):
            email = f" <{acc['email']}>" if acc["email"] else ""
            name = f" ({acc['name']})" if acc["name"] else ""
            print(f"  {idx}) {acc['profileDirectory']}{email}{name}")
        print()


def cmd_status(args):
    """Inspect current Colab MCP bridge state via background daemon."""
    try:
        data = daemon_request("GET", "/colab/status", auto_start=True)
    except Exception as e:
        _print_error(f"Failed to query status: {e}")
        return

    raw_status = (data.get("status") or "unknown").lower()
    if raw_status in ("not_connected", "ready_to_pair"):
        status_display = "[bold yellow]NOT CONNECTED (READY TO PAIR)[/bold yellow]"
        status_text = "NOT CONNECTED (READY TO PAIR)"
    elif raw_status in ("pairing", "connecting"):
        status_display = "[bold cyan]PAIRING (WAITING FOR CHROME APPROVAL)[/bold cyan]"
        status_text = "PAIRING (WAITING FOR CHROME APPROVAL)"
    elif raw_status == "connected":
        status_display = "[bold green]CONNECTED[/bold green]"
        status_text = "CONNECTED"
    elif raw_status == "disconnected":
        status_display = "[bold red]DISCONNECTED[/bold red]"
        status_text = "DISCONNECTED"
    else:
        status_display = f"[bold]{raw_status.upper()}[/bold]"
        status_text = raw_status.upper()

    message = data.get("message") or "N/A"
    gpu_info = data.get("gpu_info") or "N/A"
    tools = data.get("tools") or []
    profile = data.get("selected_profile") or "Default"
    daemon_pid = data.get("daemon_pid")

    if HAS_RICH:
        panel_content = (
            f"[bold]Status:[/bold] {status_display}\n"
            f"[bold]Message:[/bold] {message}\n"
            f"[bold]GPU Info:[/bold] {gpu_info}\n"
            f"[bold]Active Tools:[/bold] {', '.join(tools) or 'None'}\n"
            f"[bold]Selected Profile:[/bold] {profile}\n"
            f"[dim]Daemon PID: {daemon_pid}[/dim]"
        )
        console.print(Panel(panel_content, title="[bold cyan]Google Colab MCP Status[/bold cyan]"))
    else:
        print("\nGoogle Colab MCP Status:")
        print(f"  Status: {status_text}")
        print(f"  Message: {message}")
        print(f"  GPU Info: {gpu_info}")
        print(f"  Active Tools: {tools}")
        print(f"  Profile: {profile}")
        print(f"  Daemon PID: {daemon_pid}\n")


def cmd_connect(args):
    """Interactively select a profile and pair with Google Colab tab via daemon."""
    accounts_data = list_chrome_accounts()
    accounts = accounts_data.get("accounts", [])

    chosen_profile = args.profile

    if not chosen_profile and accounts:
        cmd_accounts(args)
        try:
            choice = input(f"Select profile [1-{len(accounts)}] (default: 1): ").strip()
            if not choice:
                chosen_profile = accounts[0]["profileDirectory"]
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(accounts):
                    chosen_profile = accounts[idx]["profileDirectory"]
                else:
                    _print_error("Invalid selection.")
                    return
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled.")
            return

    chosen_profile = chosen_profile or "Default"
    _print_info(f"Initiating Google Colab pairing with profile: '{chosen_profile}'...")

    def _do_connect():
        return daemon_request(
            "POST",
            "/colab/connect",
            payload={
                "profileDirectory": chosen_profile,
                "force": args.force,
                "timeout": args.timeout,
            },
            timeout=args.timeout + 20.0,
            auto_start=True,
        )

    res = None
    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}[/bold cyan]"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task("Waiting for Colab tab approval in Chrome...", total=None)
            try:
                res = _do_connect()
            except Exception as e:
                _print_error(f"Connection failed: {e}")
                return
    else:
        print("Waiting for Colab tab pairing (approve in Chrome)...")
        try:
            res = _do_connect()
        except Exception as e:
            _print_error(f"Connection failed: {e}")
            return

    if res and res.get("connected"):
        _print_success("Connected to Google Colab Cloud GPU session!")
        gpu_info = res.get("gpu_info")
        if gpu_info:
            _print_info(f"Hardware: {gpu_info}")
    else:
        msg = (res.get("message") if res else "") or f"Pairing timed out after {args.timeout}s."
        _print_error(f"{msg} Keep the Colab tab open and try again.")


def cmd_exec(args):
    """Execute Python code or a script file on the connected Colab runtime."""
    code = args.code
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                code = f.read()
        except Exception as e:
            _print_error(f"Failed to read file '{args.file}': {e}")
            return

    if not code:
        _print_error("No code provided. Use -c 'code' or -f script.py")
        return

    _print_info("Dispatching code to Google Colab GPU via background daemon...")

    try:
        res = daemon_request(
            "POST",
            "/colab/execute",
            payload={"code": code, "keep_cell": not args.temp, "timeout": 3600.0},
            timeout=3610.0,
            auto_start=True,
        )
        if res.get("isError"):
            _print_error("Remote execution encountered an error:")
            print(res.get("output", ""))
        else:
            _print_success("Execution succeeded:")
            print(res.get("output", ""))
    except Exception as e:
        _print_error(f"Execution failed: {e}")


def cmd_disconnect(args):
    """Disconnect active Google Colab GPU session."""
    try:
        res = daemon_request("POST", "/colab/disconnect", auto_start=False)
        _print_success(res.get("message", "Colab session disconnected."))
    except Exception as e:
        _print_error(f"Failed to disconnect: {e}")


def cmd_daemon(args):
    """Manage background daemon."""
    sub = args.daemon_command
    if sub == "status":
        info = get_daemon_info()
        running = is_daemon_running()
        if running and info:
            if HAS_RICH:
                content = (
                    f"[bold]Status:[/bold] RUNNING\n"
                    f"[bold]PID:[/bold] {info.get('pid')}\n"
                    f"[bold]Base URL:[/bold] {info.get('base_url')}\n"
                    f"[bold]Version:[/bold] {info.get('version')}\n"
                    f"[bold]Log File:[/bold] {DAEMON_LOG_FILE}"
                )
                console.print(Panel(content, title="[bold cyan]vspagent Daemon Status[/bold cyan]"))
            else:
                print(f"Daemon Status: RUNNING (PID: {info.get('pid')}, URL: {info.get('base_url')})")
        else:
            print("Daemon Status: STOPPED")
    elif sub == "start":
        info = ensure_daemon_running()
        _print_success(f"Daemon running at {info.get('base_url')} (PID: {info.get('pid')})")
    elif sub == "stop":
        if stop_daemon():
            _print_success("Daemon stopped.")
        else:
            _print_info("Daemon was not running.")
    elif sub == "restart":
        stop_daemon()
        time.sleep(1.0)
        info = ensure_daemon_running()
        _print_success(f"Daemon restarted at {info.get('base_url')} (PID: {info.get('pid')})")
    elif sub == "logs":
        if not DAEMON_LOG_FILE.exists():
            print("No log file found.")
            return
        lines = DAEMON_LOG_FILE.read_text(encoding="utf-8").splitlines()[-40:]
        print("\n".join(lines))
    else:
        print("Usage: vspagent daemon {status,start,stop,restart,logs}")


def cmd_serve(args):
    """Run daemon in foreground."""
    run_daemon_server(host=args.host, port=args.port)


def cmd_jarvis_list(args):
    """List JarvisLabs instances."""
    client = JarvisLabsClient()
    instances = client.list_instances()
    if not instances:
        _print_info("No JarvisLabs instances found.")
        print("Tip: Use 'vspagent jarvis adopt <IP>' to register an existing machine, or 'vspagent jarvis create' to launch one.")
        return

    if HAS_RICH:
        table = Table(title="JarvisLabs Cloud GPU Instances", show_header=True)
        table.add_column("ID / Host", style="cyan")
        table.add_column("Name", style="magenta")
        table.add_column("GPU", style="green")
        table.add_column("Status", justify="center")
        table.add_column("Active", justify="center")
        table.add_column("SSH Command", style="dim")

        active = client.get_active_instance()
        active_id = active.get("machine_id") if active else None

        for inst in instances:
            mid = inst.get("machine_id", "N/A")
            is_active = (mid == active_id)
            status_style = "green" if inst.get("status") == "Running" else "yellow"
            table.add_row(
                f"{mid}\n[dim]({inst.get('host')})[/dim]",
                inst.get("name", "instance"),
                inst.get("gpu_type", "GPU"),
                f"[{status_style}]{inst.get('status', 'Unknown')}[/{status_style}]",
                "★" if is_active else "",
                inst.get("ssh_command", "ssh root@" + str(inst.get("host"))),
            )
        console.print(table)
    else:
        print("\nJarvisLabs Instances:")
        active = client.get_active_instance()
        active_id = active.get("machine_id") if active else None
        for inst in instances:
            star = " (ACTIVE)" if inst.get("machine_id") == active_id else ""
            print(f"- {inst.get('machine_id')} [{inst.get('name')}]: {inst.get('status')} | {inst.get('gpu_type')} | Host: {inst.get('host')}{star}")
            print(f"  SSH: {inst.get('ssh_command')}")
        print()


def cmd_jarvis_status(args):
    """Show active JarvisLabs instance status."""
    client = JarvisLabsClient()
    active = client.get_active_instance()
    if not active:
        _print_error("No active JarvisLabs instance configured.")
        print("Tip: Run 'vspagent jarvis adopt <IP>' or 'vspagent jarvis list'.")
        return

    if HAS_RICH:
        panel_content = (
            f"[bold]Instance ID:[/bold] {active.get('machine_id')}\n"
            f"[bold]Name:[/bold] {active.get('name')}\n"
            f"[bold]Host / IP:[/bold] {active.get('host')}:{active.get('port', 22)}\n"
            f"[bold]GPU Type:[/bold] {active.get('gpu_type')}\n"
            f"[bold]Status:[/bold] {active.get('status')}\n"
            f"[bold]SSH Command:[/bold] {active.get('ssh_command')}\n"
            f"[bold]Jupyter URL:[/bold] {active.get('jupyter_url') or 'N/A'}"
        )
        console.print(Panel(panel_content, title="[bold cyan]Active JarvisLabs Instance[/bold cyan]"))
    else:
        print("\nActive JarvisLabs Instance:")
        print(f"  ID: {active.get('machine_id')}")
        print(f"  Name: {active.get('name')}")
        print(f"  Host: {active.get('host')}:{active.get('port', 22)}")
        print(f"  GPU: {active.get('gpu_type')}")
        print(f"  Status: {active.get('status')}")
        print(f"  SSH: {active.get('ssh_command')}\n")


def cmd_jarvis_adopt(args):
    """Adopt an existing instance by IP."""
    client = JarvisLabsClient()
    info = client.register_instance(
        host=args.host,
        machine_id=args.id,
        name=args.name or "adopted-gpu",
        gpu_type=args.gpu or "A30",
        port=args.port,
        set_active=True,
    )
    _print_success(f"Adopted JarvisLabs instance '{info['machine_id']}' ({args.host}) as active GPU instance.")


def cmd_jarvis_create(args):
    """Create a new instance."""
    client = JarvisLabsClient()
    _print_info(f"Provisioning {args.gpu} GPU instance '{args.name}' on JarvisLabs...")
    try:
        info = client.create_instance(
            gpu_type=args.gpu,
            name=args.name,
            hdd=args.hdd,
            template=args.template,
        )
        _print_success(f"Instance created: {info.get('machine_id')} ({info.get('host')})")
        print(f"SSH: {info.get('ssh_command')}")
    except Exception as e:
        _print_error(f"Failed to create instance: {e}")


def cmd_jarvis_pause(args):
    """Pause an instance to halt compute billing."""
    client = JarvisLabsClient()
    _print_info(f"Pausing instance {args.id or '(active)'} to stop compute billing...")
    try:
        client.pause(args.id)
        _print_success("Instance paused successfully. Compute billing stopped.")
    except Exception as e:
        _print_error(f"Failed to pause instance: {e}")


def cmd_jarvis_resume(args):
    """Resume a paused instance."""
    client = JarvisLabsClient()
    _print_info(f"Resuming instance {args.id or '(active)'}...")
    try:
        client.resume(args.id, gpu_type=args.gpu)
        _print_success("Instance resumed successfully.")
    except Exception as e:
        _print_error(f"Failed to resume instance: {e}")


def cmd_jarvis_destroy(args):
    """Destroy an instance."""
    client = JarvisLabsClient()
    confirm = args.yes
    if not confirm:
        val = input(f"Are you sure you want to PERMANENTLY destroy instance {args.id or '(active)'}? [y/N]: ")
        if val.lower() not in ("y", "yes"):
            _print_info("Destruction canceled.")
            return

    try:
        client.destroy(args.id)
        _print_success("Instance destroyed permanently.")
    except Exception as e:
        _print_error(f"Failed to destroy instance: {e}")


def cmd_jarvis_exec(args):
    """Execute command or python file on GPU instance."""
    client = JarvisLabsClient()
    if not args.code and not args.file:
        _print_error("Please specify either -c 'command' or -f file.py to execute.")
        return

    try:
        if args.file:
            _print_info(f"Uploading and running {args.file} on remote GPU...")
            code, out = client.run_script(args.file, instance_id=args.id, script_args=args.args)
        else:
            _print_info(f"Executing remote command: {args.code}")
            code, out = client.exec(args.code, instance_id=args.id, workdir=args.workdir, stream=True)

        if code == 0:
            _print_success("Remote execution completed with exit code 0.")
        else:
            _print_error(f"Remote command failed with exit code {code}.")
    except Exception as e:
        _print_error(f"Execution failed: {e}")


def cmd_jarvis_ssh(args):
    """SSH into GPU instance."""
    client = JarvisLabsClient()
    if args.print_only:
        inst = client.get_active_instance()
        if inst:
            print(inst.get("ssh_command", f"ssh root@{inst.get('host')}"))
        else:
            _print_error("No active instance.")
        return
    client.interactive_ssh(instance_id=args.id)


def cmd_jarvis_sync(args):
    """Sync files up or down."""
    client = JarvisLabsClient()
    try:
        if args.direction == "up":
            _print_info(f"Uploading {args.src} -> remote:{args.dest}...")
            ok = client.sync_up(args.src, remote_path=args.dest, instance_id=args.id)
        else:
            _print_info(f"Downloading remote:{args.src} -> {args.dest}...")
            ok = client.sync_down(args.src, local_path=args.dest, instance_id=args.id)
        if ok:
            _print_success("Sync completed successfully.")
        else:
            _print_error("Sync failed.")
    except Exception as e:
        _print_error(f"Sync error: {e}")


def cmd_jarvis_tunnel(args):
    """Establish port tunnel."""
    client = JarvisLabsClient()
    try:
        info = client.tunnel(
            remote_port=args.remote_port,
            local_port=args.local_port,
            instance_id=args.id,
        )
        _print_success(f"SSH Tunnel established! Remote port {args.remote_port} forwarded to {info['url']}")
        print(f"Local endpoint: {info['url']} (PID: {info['pid']})")
    except Exception as e:
        _print_error(f"Tunnel creation failed: {e}")


def cmd_jarvis_tunnels(args):
    """List active port tunnels."""
    tunnels = list_active_tunnels()
    if not tunnels:
        _print_info("No active SSH tunnels.")
        return

    if HAS_RICH:
        table = Table(title="Active Remote GPU Port Tunnels", show_header=True)
        table.add_column("Local URL", style="green")
        table.add_column("Remote Host:Port", style="cyan")
        table.add_column("PID", style="magenta")
        for t in tunnels:
            table.add_row(
                t.get("url", f"http://localhost:{t.get('local_port')}"),
                f"{t.get('remote_host')}:{t.get('remote_port')}",
                str(t.get("pid", "N/A")),
            )
        console.print(table)
    else:
        print("\nActive Tunnels:")
        for t in tunnels:
            print(f"- Local: {t.get('url')} -> Remote {t.get('remote_host')}:{t.get('remote_port')} (PID: {t.get('pid')})")
        print()


def cmd_jarvis_untunnel(args):
    """Stop active port tunnel."""
    ok = stop_ssh_tunnel(args.local_port)
    if ok:
        _print_success(f"Tunnel on local port {args.local_port} stopped.")
    else:
        _print_info(f"No active tunnel found on local port {args.local_port}.")


def main():
    parser = argparse.ArgumentParser(
        prog="vspagent",
        description="vspagent: Zero-local-GPU Cloud Agent Harness via Google Colab MCP",
    )
    parser.add_argument("--version", action="version", version=f"vspagent {__version__}")

    subparsers = parser.add_subparsers(dest="subcommand")

    # colab commands
    colab_parser = subparsers.add_parser("colab", help="Colab MCP commands")
    colab_subs = colab_parser.add_subparsers(dest="colab_command")

    # accounts
    colab_subs.add_parser("accounts", help="List Chrome profiles and Google accounts")

    # status
    colab_subs.add_parser("status", help="Show Colab MCP connection status and GPU info")

    # connect
    conn_p = colab_subs.add_parser("connect", help="Pair with a Google Colab notebook session")
    conn_p.add_argument("-p", "--profile", help="Chrome profile directory (e.g. 'Default', 'Profile 1')")
    conn_p.add_argument("-f", "--force", action="store_true", help="Force reconnect if already active")
    conn_p.add_argument("-t", "--timeout", type=float, default=90.0, help="Pairing timeout in seconds")

    # exec
    exec_p = colab_subs.add_parser("exec", help="Run Python code on Colab GPU")
    exec_p.add_argument("-c", "--code", help="Inline Python string to execute")
    exec_p.add_argument("-f", "--file", help="Python file path to execute remotely")
    exec_p.add_argument("--temp", action="store_true", help="Delete the cell after execution")

    # disconnect
    colab_subs.add_parser("disconnect", help="Disconnect active Colab session")

    # daemon commands
    daemon_parser = subparsers.add_parser("daemon", help="Manage background daemon")
    daemon_subs = daemon_parser.add_subparsers(dest="daemon_command")
    daemon_subs.add_parser("status", help="Show daemon status")
    daemon_subs.add_parser("start", help="Start background daemon")
    daemon_subs.add_parser("stop", help="Stop background daemon")
    daemon_subs.add_parser("restart", help="Restart background daemon")
    daemon_subs.add_parser("logs", help="View recent daemon logs")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Run vspagent daemon server in foreground")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=4096, help="Port to bind (default: 4096)")

    # jarvis commands
    jarvis_parser = subparsers.add_parser("jarvis", help="JarvisLabs Cloud GPU commands")
    jarvis_subs = jarvis_parser.add_subparsers(dest="jarvis_command")

    # list
    jarvis_subs.add_parser("list", help="List all JarvisLabs instances")

    # status
    jarvis_subs.add_parser("status", help="Show active JarvisLabs instance status and specs")

    # adopt / register
    adopt_p = jarvis_subs.add_parser("adopt", help="Adopt an existing running JarvisLabs instance by IP")
    adopt_p.add_argument("host", help="IP address or hostname of the instance")
    adopt_p.add_argument("--id", help="Custom identifier for the instance")
    adopt_p.add_argument("--name", default="gpu-instance", help="Display name")
    adopt_p.add_argument("--gpu", default="A30", help="GPU model (e.g. A30, A100, RTX6000)")
    adopt_p.add_argument("-p", "--port", type=int, default=22, help="SSH port")

    # create
    create_p = jarvis_subs.add_parser("create", help="Create a new GPU instance on JarvisLabs")
    create_p.add_argument("--gpu", default="A30", help="GPU type (e.g. A30, A100, H100)")
    create_p.add_argument("--name", default="gpu-worker", help="Instance name")
    create_p.add_argument("--hdd", type=int, default=25, help="Disk size in GB (default: 25)")
    create_p.add_argument("--template", default="pytorch", help="Template name (default: pytorch)")

    # pause
    pause_p = jarvis_subs.add_parser("pause", help="Pause an instance to stop compute billing")
    pause_p.add_argument("id", nargs="?", help="Instance ID (optional, defaults to active instance)")

    # resume
    resume_p = jarvis_subs.add_parser("resume", help="Resume a paused instance")
    resume_p.add_argument("id", nargs="?", help="Instance ID (optional, defaults to active instance)")
    resume_p.add_argument("--gpu", help="Optional new GPU type when resuming")

    # destroy
    destroy_p = jarvis_subs.add_parser("destroy", help="Permanently destroy instance")
    destroy_p.add_argument("id", nargs="?", help="Instance ID (optional, defaults to active instance)")
    destroy_p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # exec
    exec_j = jarvis_subs.add_parser("exec", help="Run a bash command or Python script remotely on GPU")
    exec_j.add_argument("-c", "--code", help="Command string to execute remotely")
    exec_j.add_argument("-f", "--file", help="Local Python file to upload and execute remotely")
    exec_j.add_argument("--args", help="Arguments to pass to the script")
    exec_j.add_argument("--workdir", default="/home", help="Remote working directory (default: /home)")
    exec_j.add_argument("--id", help="Instance ID to target")

    # ssh
    ssh_p = jarvis_subs.add_parser("ssh", help="Connect to the instance via interactive SSH")
    ssh_p.add_argument("id", nargs="?", help="Instance ID (optional)")
    ssh_p.add_argument("--print-only", action="store_true", help="Print the SSH command instead of launching shell")

    # sync
    sync_p = jarvis_subs.add_parser("sync", help="Upload or download files between local and remote GPU")
    sync_p.add_argument("direction", choices=["up", "down"], help="'up' to upload, 'down' to download")
    sync_p.add_argument("src", help="Source file or directory path")
    sync_p.add_argument("dest", help="Destination path")
    sync_p.add_argument("--id", help="Instance ID to target")

    # tunnel
    tunnel_p = jarvis_subs.add_parser("tunnel", help="Forward a remote service port to localhost")
    tunnel_p.add_argument("remote_port", type=int, help="Remote port (e.g. 8000 for FastAPI / Gradio / WebSocket)")
    tunnel_p.add_argument("-l", "--local-port", type=int, help="Local port (defaults to same as remote_port)")
    tunnel_p.add_argument("--id", help="Instance ID to target")

    # tunnels
    jarvis_subs.add_parser("tunnels", help="List active SSH port tunnels")

    # untunnel
    untunnel_p = jarvis_subs.add_parser("untunnel", help="Stop an SSH port tunnel")
    untunnel_p.add_argument("local_port", type=int, help="Local port to disconnect")

    args = parser.parse_args()

    if args.subcommand == "colab":
        if args.colab_command == "accounts":
            cmd_accounts(args)
        elif args.colab_command == "status":
            cmd_status(args)
        elif args.colab_command == "connect":
            cmd_connect(args)
        elif args.colab_command == "exec":
            cmd_exec(args)
        elif args.colab_command == "disconnect":
            cmd_disconnect(args)
        else:
            colab_parser.print_help()
    elif args.subcommand == "jarvis":
        if args.jarvis_command == "list":
            cmd_jarvis_list(args)
        elif args.jarvis_command == "status":
            cmd_jarvis_status(args)
        elif args.jarvis_command == "adopt":
            cmd_jarvis_adopt(args)
        elif args.jarvis_command == "create":
            cmd_jarvis_create(args)
        elif args.jarvis_command == "pause":
            cmd_jarvis_pause(args)
        elif args.jarvis_command == "resume":
            cmd_jarvis_resume(args)
        elif args.jarvis_command == "destroy":
            cmd_jarvis_destroy(args)
        elif args.jarvis_command == "exec":
            cmd_jarvis_exec(args)
        elif args.jarvis_command == "ssh":
            cmd_jarvis_ssh(args)
        elif args.jarvis_command == "sync":
            cmd_jarvis_sync(args)
        elif args.jarvis_command == "tunnel":
            cmd_jarvis_tunnel(args)
        elif args.jarvis_command == "tunnels":
            cmd_jarvis_tunnels(args)
        elif args.jarvis_command == "untunnel":
            cmd_jarvis_untunnel(args)
        else:
            jarvis_parser.print_help()
    elif args.subcommand == "daemon":
        cmd_daemon(args)
    elif args.subcommand == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
