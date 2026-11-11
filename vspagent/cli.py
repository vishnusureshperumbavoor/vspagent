"""Command line entrypoint for the vspagent coding agent."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from vspagent import __version__, auth
from vspagent.agent import Agent
from vspagent.agent.providers import OpenAICompatibleProvider, ProviderError
from vspagent.agent.tools import Workspace, default_registry
from vspagent.agent.ui.repl import Repl, RichUI, one_shot
from vspagent.config import (
    PERMISSION_MODES,
    Config,
    ConfigError,
    config_path,
    load_config,
    render_default_config,
    write_default_config,
)
from vspagent.permissions import PermissionManager
from vspagent.security import mask_secret, redact
from vspagent.session import SessionStore

SUBCOMMANDS = {"auth", "models", "config", "sessions"}
console = Console()


def build_agent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vspagent",
        description="Terminal coding agent powered by OpenAI-compatible LLM APIs.",
    )
    parser.add_argument("--version", action="version", version=f"vspagent {__version__}")
    parser.add_argument("--provider", help="Provider name (default: kimi)")
    parser.add_argument("--model", help="Model name; defaults to the provider config")
    parser.add_argument("--cwd", help="Workspace directory (default: current directory)")
    parser.add_argument("--permission-mode", choices=PERMISSION_MODES, help="ask, allowlist or yolo")
    parser.add_argument("--session", help="Resume a session id")
    parser.add_argument("--continue", dest="continue_session", action="store_true", help="Resume the latest session")
    parser.add_argument("--max-iterations", type=int, help="Maximum tool rounds per turn")
    parser.add_argument("--show-reasoning", action="store_true", help="Print reasoning tokens")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt; omit for an interactive session")
    return parser


def build_auth_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vspagent auth", description="Manage provider API keys")
    sub = parser.add_subparsers(dest="auth_command")
    login = sub.add_parser("login", help="Store a provider API key")
    login.add_argument("provider", nargs="?", help="Provider name")
    login.add_argument("--stdin", action="store_true", help="Read the key from stdin")
    sub.add_parser("status", help="Show configured keys without revealing them")
    logout = sub.add_parser("logout", help="Remove a stored key")
    logout.add_argument("provider", nargs="?", help="Provider name")
    return parser


def build_models_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vspagent models", description="List provider models")
    parser.add_argument("--provider", help="Provider name")
    return parser


def build_config_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vspagent config", description="Show or create config")
    parser.add_argument("--init", action="store_true", help="Write a starter config")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing config")
    parser.add_argument("--show", action="store_true", help="Print the config path and contents")
    return parser


def build_sessions_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vspagent sessions", description="Inspect sessions")
    sub = parser.add_subparsers(dest="session_command")
    sub.add_parser("list", help="List recent sessions")
    delete = sub.add_parser("delete", help="Delete a session")
    delete.add_argument("id")
    return parser


def _apply_overrides(config: Config, args: argparse.Namespace) -> None:
    if getattr(args, "provider", None):
        config.provider = args.provider.strip().lower()
    if getattr(args, "model", None):
        config.model = args.model.strip()
    if getattr(args, "permission_mode", None):
        config.permission_mode = args.permission_mode
    if getattr(args, "max_iterations", None):
        config.max_iterations = max(1, args.max_iterations)


def _provider_for(config: Config, provider_name: str | None = None) -> OpenAICompatibleProvider:
    provider = config.provider_config(provider_name)
    key = auth.get_key(provider.name, provider.api_key_env)
    if not key and provider.auth_style != "none":
        raise ConfigError(
            f"no API key for {provider.name}; run `vspagent auth login {provider.name}` "
            f"or set {provider.api_key_env or 'VSPAGENT_API_KEY'}"
        )
    return OpenAICompatibleProvider(provider, key, timeout=config.timeout)


def _open_session(args: argparse.Namespace, config: Config, store: SessionStore, cwd: Path):
    if args.session:
        return store.load(args.session)
    if args.continue_session:
        session = store.latest()
        if session:
            return session
        console.print("[dim]No previous session; starting a new one.[/dim]")
    return store.new(config.provider, config.provider_config().model, str(cwd))


def _run_agent(args: argparse.Namespace) -> int:
    config = load_config()
    _apply_overrides(config, args)
    provider = _provider_for(config)
    store = SessionStore()
    session = _open_session(args, config, store, Path(args.cwd or os.getcwd()).resolve())
    if args.cwd:
        cwd = Path(args.cwd).expanduser().resolve()
    elif session.cwd:
        cwd = Path(session.cwd).expanduser()
    else:
        cwd = Path.cwd()
    workspace = Workspace(cwd)
    session.provider = provider.provider.name
    session.model = provider.provider.model
    session.cwd = str(workspace.root)
    ui = RichUI(show_reasoning=args.show_reasoning)
    permissions = PermissionManager(config.permission_mode, prompt=ui.confirm)
    agent = Agent(
        provider,
        default_registry(),
        permissions,
        session,
        workspace,
        ui=ui,
        max_iterations=config.max_iterations,
    )
    prompt = " ".join(args.prompt).strip()
    try:
        if prompt:
            return one_shot(agent, prompt, store)
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
            if prompt:
                return one_shot(agent, prompt, store)
        return Repl(agent, provider, permissions, session, config, store, ui).run()
    finally:
        provider.close()


def _cmd_auth(argv: list[str]) -> int:
    args = build_auth_parser().parse_args(argv)
    config = load_config()
    if args.auth_command == "login":
        provider_name = (args.provider or config.provider).strip().lower()
        provider = config.provider_config(provider_name)
        name, backend = auth.login(provider.name, from_stdin=args.stdin)
        value = auth.get_key(provider.name, provider.api_key_env)
        console.print(f"Stored {name} key in {backend} ({mask_secret(value)}).")
        return 0
    if args.auth_command == "logout":
        provider_name = (args.provider or config.provider).strip().lower()
        config.provider_config(provider_name)
        removed = auth.delete_key(provider_name)
        console.print(f"Removed {provider_name} key." if removed else f"No stored key for {provider_name}.")
        return 0
    providers = {name: provider.api_key_env for name, provider in config.providers.items()}
    table = Table(title="vspagent credentials")
    for column in ("provider", "source", "key"):
        table.add_column(column)
    for row in auth.status(providers):
        table.add_row(row["provider"], row["source"], row["key"])
    console.print(table)
    return 0


def _cmd_models(argv: list[str]) -> int:
    args = build_models_parser().parse_args(argv)
    config = load_config()
    provider = _provider_for(config, args.provider)
    try:
        models = provider.list_models()
        for model in models:
            print(model)
        return 0
    finally:
        provider.close()


def _cmd_config(argv: list[str]) -> int:
    args = build_config_parser().parse_args(argv)
    if args.init:
        target = write_default_config(force=args.force)
        console.print(f"Wrote {target}")
        return 0
    config = load_config()
    target = config.path or config_path()
    console.print(f"[bold]path:[/bold] {target} ({'exists' if target.exists() else 'not created'})")
    console.print(render_default_config(config))
    return 0


def _cmd_sessions(argv: list[str]) -> int:
    args = build_sessions_parser().parse_args(argv)
    store = SessionStore()
    if args.session_command == "delete":
        console.print("Deleted." if store.delete(args.id) else "Session not found.")
        return 0
    sessions = store.list()
    if not sessions:
        console.print("No sessions yet.")
        return 0
    table = Table(title="vspagent sessions")
    for column in ("id", "updated", "provider", "model", "title"):
        table.add_column(column, overflow="fold")
    for session in sessions:
        import time

        table.add_row(
            session.id,
            time.strftime("%Y-%m-%d %H:%M", time.localtime(session.updated_at)),
            session.provider,
            session.model,
            session.title or "—",
        )
    console.print(table)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    try:
        if arguments and arguments[0] in SUBCOMMANDS:
            command, rest = arguments[0], arguments[1:]
            if command == "auth":
                return _cmd_auth(rest)
            if command == "models":
                return _cmd_models(rest)
            if command == "config":
                return _cmd_config(rest)
            return _cmd_sessions(rest)
        args = build_agent_parser().parse_args(arguments)
        return _run_agent(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except (ConfigError, ProviderError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
