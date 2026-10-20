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

    status = (data.get("status") or "unknown").upper()
    message = data.get("message") or "N/A"
    gpu_info = data.get("gpu_info") or "N/A"
    tools = data.get("tools") or []
    profile = data.get("selected_profile") or "Default"
    daemon_pid = data.get("daemon_pid")

    if HAS_RICH:
        panel_content = (
            f"[bold]Status:[/bold] {status}\n"
            f"[bold]Message:[/bold] {message}\n"
            f"[bold]GPU Info:[/bold] {gpu_info}\n"
            f"[bold]Active Tools:[/bold] {', '.join(tools) or 'None'}\n"
            f"[bold]Selected Profile:[/bold] {profile}\n"
            f"[dim]Daemon PID: {daemon_pid}[/dim]"
        )
        console.print(Panel(panel_content, title="[bold cyan]Google Colab MCP Status[/bold cyan]"))
    else:
        print("\nGoogle Colab MCP Status:")
        print(f"  Status: {status}")
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
    elif args.subcommand == "daemon":
        cmd_daemon(args)
    elif args.subcommand == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
