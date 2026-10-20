"""Web framework integrations for vspagent."""

from vspagent.colab.integrations.fastapi import get_colab_router
from vspagent.colab.integrations.flask import get_colab_blueprint

__all__ = ["get_colab_router", "get_colab_blueprint"]
