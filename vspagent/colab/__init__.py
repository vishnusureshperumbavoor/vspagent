"""vspagent Google Colab MCP agent orchestrator."""

from vspagent.colab.client import ColabClient, ColabMCPClient, internal_colab_client
from vspagent.colab.profiles import (
    list_chrome_accounts,
    discover_chrome_accounts,
    set_selected_profile,
    get_selected_profile,
    open_url_with_profile,
)

__all__ = [
    "ColabClient",
    "ColabMCPClient",
    "internal_colab_client",
    "list_chrome_accounts",
    "discover_chrome_accounts",
    "set_selected_profile",
    "get_selected_profile",
    "open_url_with_profile",
]
