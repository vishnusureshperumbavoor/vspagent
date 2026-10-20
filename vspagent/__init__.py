"""vspagent: Universal Google Colab MCP Engine & Remote Cloud GPU Orchestration SDK."""

__version__ = "3.0.0"
__author__ = "Vishnu Suresh Perumbavoor"

from vspagent.colab.client import ColabClient, ColabMCPClient, internal_colab_client
from vspagent.colab.profiles import (
    list_chrome_accounts,
    set_selected_profile,
    get_selected_profile,
    open_url_with_profile,
)

__all__ = [
    "ColabClient",
    "ColabMCPClient",
    "internal_colab_client",
    "list_chrome_accounts",
    "set_selected_profile",
    "get_selected_profile",
    "open_url_with_profile",
    "__version__",
]
