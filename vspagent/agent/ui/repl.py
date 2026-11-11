"""Rich + prompt_toolkit terminal UI."""

from __future__ import annotations

import sys
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.rule import Rule
from rich.table import Table

from vspagent.agent.loop import Agent, AgentUI
from vspagent.agent.providers import OpenAICompatibleProvider
from vspagent.config import Config, history_path
from vspagent.permissions import PermissionManager
from vspagent.security import redact, sanitize_terminal
from vspagent.session import Session, SessionStore


class RichUI(AgentUI):
    def __init__(self, console: Console | None = None, show_reasoning: bool = False) -> None:
        self.console = console or Console()
        self.show_reasoning = show_reasoning
        self._in_text = False

    def on_text(self, text: str) -> None:
        self._in_text = True
        self.console.print(
            sanitize_terminal(text), end="", markup=False, highlight=False, soft_wrap=True
        )

    def on_reasoning(self, text: str) -> None:
        if self.show_reasoning:
            self.console.print(
                sanitize_terminal(text), end="", style="dim italic", markup=False, highlight=False
            )

    def on_tool_call(self, name: str, arguments: dict[str, Any], summary: str) -> None:
        self._newline()
        self.console.print(Rule(style="dim"))
        self.console.print(f"[bold cyan]⚙ {escape(name)}[/bold cyan] [dim]{escape(redact(summary))}[/dim]")

    def on_tool_result(self, name: str, result: str) -> None:
        text = result if len(result) <= 4000 else result[:4000] + "\n… truncated"
        self.console.print(escape(sanitize_terminal(text)), style="dim")

    def on_notice(self, text: str) -> None:
        self._newline()
        if text:
            self.console.print(f"[dim]{escape(text)}[/dim]")

    def confirm(self, summary: str) -> bool:
        self._newline()
        try:
            return bool(Confirm.ask(f"Allow {escape(summary)}?", default=False))
        except (EOFError, KeyboardInterrupt):
            return False

    def _newline(self) -> None:
        if self._in_text:
            self.console.print()
            self._in_text = False


class Repl:
    def __init__(
        self,
        agent: Agent,
        provider: OpenAICompatibleProvider,
        permissions: PermissionManager,
        session: Session,
        config: Config,
        store: SessionStore,
        ui: RichUI,
    ) -> None:
        self.agent = agent
        self.provider = provider
        self.permissions = permissions
        self.session = session
        self.config = config
        self.store = store
        self.ui = ui
        self.console = ui.console
        self.prompt = self._prompt_session()

    def _prompt_session(self) -> PromptSession:
        target = history_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        return PromptSession(history=FileHistory(str(target)))

    def banner(self) -> None:
        self.console.print(
            Panel(
                f"[bold]vspagent[/bold]  provider=[cyan]{self.provider.provider.name}[/cyan]  "
                f"model=[green]{self.provider.provider.model}[/green]\n"
                f"cwd={self.agent.workspace.root}  permissions={self.permissions.mode}  "
                f"session={self.session.id}\n"
                "[dim]/help for commands, Ctrl-D to exit[/dim]",
                title="terminal coding agent",
                border_style="cyan",
            )
        )

    def run(self) -> int:
        self.banner()
        while True:
            try:
                text = self.prompt.prompt("vspagent> ").strip()
            except KeyboardInterrupt:
                self.console.print("\n[dim]Cancelled.[/dim]")
                continue
            except EOFError:
                self.console.print()
                self._save()
                return 0
            if not text:
                continue
            if text.startswith("/"):
                if not self.command(text):
                    self._save()
                    return 0
                continue
            try:
                self.agent.run(text)
            except Exception as exc:  # noqa: BLE001 - a failed turn must not kill the REPL
                self.console.print(f"[bold red]Error:[/bold red] {escape(redact(str(exc)))}")
            self._save()
            self.console.print()

    def _save(self) -> None:
        try:
            self.store.save(self.session)
        except OSError as exc:
            self.console.print(f"[yellow]Could not save session: {escape(str(exc))}[/yellow]")

    def command(self, text: str) -> bool:
        """Run a slash command. Return False to exit."""
        parts = text.split()
        command = parts[0].lower()
        argument = " ".join(parts[1:]).strip()
        if command in {"/quit", "/exit", "/q"}:
            return False
        if command in {"/help", "/?"}:
            self._help()
        elif command == "/clear":
            self.session.messages.clear()
            self.session.usage.clear()
            self.console.print("[dim]Conversation cleared.[/dim]")
        elif command == "/compact":
            self.session.compact()
            self.console.print("[dim]Conversation compacted.[/dim]")
        elif command == "/model":
            self._model(argument)
        elif command == "/models":
            self._models()
        elif command == "/provider":
            self.console.print(
                f"{self.provider.provider.name}  {self.provider.provider.base_url}  "
                f"{self.provider.provider.model}"
            )
        elif command == "/permissions":
            self._permissions(argument)
        elif command == "/session":
            self.console.print(
                f"id={self.session.id}  messages={len(self.session.messages)}  "
                f"usage={self.session.usage or {}}"
            )
        elif command == "/tools":
            self.console.print(", ".join(self.agent.registry.names()))
        else:
            self.console.print(f"[yellow]Unknown command: {escape(command)}[/yellow]")
        return True

    def _model(self, argument: str) -> None:
        if not argument:
            self.console.print(self.provider.provider.model)
            return
        self.provider.provider.model = argument
        self.session.model = argument
        self.console.print(f"[dim]Model set to {escape(argument)}.[/dim]")

    def _models(self) -> None:
        try:
            models = self.provider.list_models()
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[bold red]Error:[/bold red] {escape(redact(str(exc)))}")
            return
        table = Table(title=f"{self.provider.provider.name} models", show_header=False)
        for model in models:
            table.add_row(model)
        self.console.print(table)

    def _permissions(self, argument: str) -> None:
        if argument in {"ask", "allowlist", "yolo"}:
            self.permissions.mode = argument
            self.config.permission_mode = argument
            self.console.print(f"[dim]Permission mode: {argument}[/dim]")
        else:
            self.console.print(
                f"permission mode: {self.permissions.mode} (use /permissions ask|allowlist|yolo)"
            )

    def _help(self) -> None:
        self.console.print(
            "\n".join(
                [
                    "/help                 show this help",
                    "/model [name]         show or change the model",
                    "/models               list models from the provider",
                    "/provider              show provider details",
                    "/permissions [mode]   ask | allowlist | yolo",
                    "/clear                clear the conversation",
                    "/compact              trim old history",
                    "/session              session id and token usage",
                    "/tools                list available tools",
                    "/quit                 exit",
                ]
            )
        )


def one_shot(agent: Agent, prompt: str, store: SessionStore) -> int:
    """Run a single prompt and save the session."""
    try:
        agent.run(prompt)
    except Exception as exc:  # noqa: BLE001 - CLI converts this to one sentence
        print(f"Error: {redact(str(exc))}", file=sys.stderr)
        return 1
    try:
        store.save(agent.session)
    except OSError:
        pass
    print()
    return 0
