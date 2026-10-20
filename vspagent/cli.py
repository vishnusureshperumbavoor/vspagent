"""Command Line Interface for vspagent: Google Colab MCP Agent Orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

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

from vspagent.colab.client import internal_colab_client
from vspagent.colab.profiles import list_chrome_accounts, set_selected_profile


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
                "★" if acc["isDefault"] else ""
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
    """Inspect current Colab MCP bridge state."""
    async def _check():
        await internal_colab_client.start()
        await asyncio.sleep(1.0)
        return internal_colab_client

    client = asyncio.run(_check())

    if HAS_RICH:
        panel_content = (
            f"[bold]Status:[/bold] {client.status.upper()}\n"
            f"[bold]Message:[/bold] {client.status_message}\n"
            f"[bold]GPU Info:[/bold] {client.gpu_info or 'N/A'}\n"
            f"[bold]Active Tools:[/bold] {', '.join(client.tools.keys()) or 'None'}\n"
            f"[bold]Selected Profile:[/bold] {client.selected_profile or 'Default'}"
        )
        console.print(Panel(panel_content, title="[bold cyan]Google Colab MCP Status[/bold cyan]"))
    else:
        print("\nGoogle Colab MCP Status:")
        print(f"  Status: {client.status}")
        print(f"  Message: {client.status_message}")
        print(f"  GPU Info: {client.gpu_info or 'N/A'}")
        print(f"  Active Tools: {list(client.tools.keys())}")
        print(f"  Profile: {client.selected_profile}\n")


def cmd_connect(args):
    """Interactively select a profile and pair with Google Colab tab."""
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

    async def _connect():
        res = await internal_colab_client.connect_browser(
            profile_directory=chosen_profile, force=args.force
        )
        if internal_colab_client.status == "connected":
            return True

        # Wait for user approval in Chrome
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            if internal_colab_client.status == "connected":
                return True
        return False

    success = False
    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}[/bold cyan]"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Waiting for Colab tab approval in Chrome...", total=None)
            success = asyncio.run(_connect())
    else:
        print("Waiting for Colab tab pairing (approve in Chrome)...")
        success = asyncio.run(_connect())

    if success:
        _print_success("Connected to Google Colab Cloud GPU session!")
        if internal_colab_client.gpu_info:
            _print_info(f"Hardware: {internal_colab_client.gpu_info}")
    else:
        _print_error(f"Pairing timed out after {args.timeout}s. Keep the Colab tab open and try again.")


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

    _print_info("Dispatching code to Google Colab GPU...")

    async def _run():
        return await internal_colab_client.execute_code(code, keep_cell=not args.temp)

    try:
        res = asyncio.run(_run())
        if res.get("isError"):
            _print_error("Remote execution encountered an error:")
            print(res.get("output", ""))
        else:
            _print_success("Execution succeeded:")
            print(res.get("output", ""))
    except Exception as e:
        _print_error(f"Execution failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="vspagent",
        description="vspagent: Zero-local-GPU Cloud Orchestration via Google Colab MCP",
    )
    parser.add_argument("--version", action="version", version="vspagent 3.0.1")

    subparsers = parser.add_subparsers(dest="subcommand")

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
        else:
            colab_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
