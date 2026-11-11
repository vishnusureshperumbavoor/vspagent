"""Default coding tools."""

from vspagent.agent.tools.base import (
    TodoList,
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    Workspace,
    int_argument,
    load_arguments,
)
from vspagent.agent.tools.files import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from vspagent.agent.tools.search import GlobTool, GrepTool
from vspagent.agent.tools.shell import ShellTool, TodoTool


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
            ListDirTool(),
            GlobTool(),
            GrepTool(),
            ShellTool(),
            TodoTool(),
        ]
    )


__all__ = [
    "EditFileTool",
    "GlobTool",
    "GrepTool",
    "ListDirTool",
    "ReadFileTool",
    "ShellTool",
    "TodoList",
    "TodoTool",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "Workspace",
    "WriteFileTool",
    "default_registry",
    "int_argument",
    "load_arguments",
]
