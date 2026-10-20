"""vspagent: Universal Google Colab MCP Agent Harness & Cloud GPU SDK."""

__version__ = "3.1.0"
__author__ = "Vishnu Suresh Perumbavoor"

from vspagent.colab.client import ColabClient, ColabMCPClient, internal_colab_client
from vspagent.daemon import (
    ensure_daemon_running,
    get_daemon_info,
    is_daemon_running,
    stop_daemon,
)
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
    "ensure_daemon_running",
    "get_daemon_info",
    "is_daemon_running",
    "stop_daemon",
    "list_chrome_accounts",
    "discover_chrome_accounts",
    "set_selected_profile",
    "get_selected_profile",
    "open_url_with_profile",
    "__version__",
]
