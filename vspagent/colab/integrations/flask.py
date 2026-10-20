"""Flask integration blueprint for vspagent Google Colab MCP agent orchestrator."""

from __future__ import annotations

from typing import Any, Optional

try:
    from flask import Blueprint, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


def get_colab_blueprint(name: str = "vspagent_colab") -> Any:
    """Returns a configured Flask Blueprint for Colab MCP routes."""
    if not FLASK_AVAILABLE:
        raise ImportError(
            "Flask is required to use get_colab_blueprint(). Install with `pip install flask`."
        )

    from vspagent.colab.client import internal_colab_client
    from vspagent.colab.profiles import list_chrome_accounts

    bp = Blueprint(name, __name__)

    @bp.route("/status", methods=["GET"])
    def get_status():
        return jsonify({
            "status": internal_colab_client.status,
            "message": internal_colab_client.status_message,
            "gpu_info": internal_colab_client.gpu_info,
            "profileDirectory": internal_colab_client.selected_profile,
            "tools": list(internal_colab_client.tools.keys()),
            "connected": internal_colab_client.status == "connected",
            "colabAvailable": internal_colab_client.status == "connected",
            "recent_logs": list(internal_colab_client.logs)[-25:],
        })

    @bp.route("/accounts", methods=["GET"])
    def get_accounts():
        return jsonify(list_chrome_accounts())

    @bp.route("/connect", methods=["POST"])
    def connect():
        data = request.get_json(silent=True) or {}
        profile = data.get("profileDirectory")
        force = bool(data.get("force", False))
        try:
            res = internal_colab_client.run_sync(
                internal_colab_client.connect_browser(profile_directory=profile, force=force)
            )
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/execute", methods=["POST"])
    def execute():
        if internal_colab_client.status != "connected":
            return jsonify({
                "status": "error",
                "message": "Colab GPU runtime is not connected. Call POST /connect first.",
            }), 400

        data = request.get_json(silent=True) or {}
        code = data.get("code")
        if not code:
            return jsonify({"status": "error", "message": "Missing 'code' parameter."}), 400

        keep_cell = bool(data.get("keep_cell", True))
        timeout = float(data.get("timeout", 3600.0))

        try:
            res = internal_colab_client.run_sync(
                internal_colab_client.execute_code(code, keep_cell=keep_cell, timeout=timeout)
            )
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/disconnect", methods=["POST"])
    def disconnect():
        internal_colab_client.run_sync(internal_colab_client.disconnect())
        return jsonify({"status": "disconnected"})

    return bp
