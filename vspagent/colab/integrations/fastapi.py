"""FastAPI integration router for vspagent Google Colab MCP agent harness."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

try:
    from fastapi import APIRouter, HTTPException
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


class ExecuteRequest(BaseModel):
    code: str
    keep_cell: bool = True
    timeout: float = 3600.0


class ConnectRequest(BaseModel):
    profileDirectory: Optional[str] = Field(
        default=None,
        description="Chrome profile directory, e.g. 'Default', 'Profile 1'",
    )
    force: bool = Field(
        default=False,
        description="Force reconnection even if already connected",
    )


def get_colab_router() -> Any:
    """Returns a configured FastAPI APIRouter for Colab MCP routes."""
    if not FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is required to use get_colab_router(). Install with `pip install fastapi`."
        )

    from vspagent.colab.client import internal_colab_client
    from vspagent.colab.profiles import list_chrome_accounts

    router = APIRouter(prefix="/colab", tags=["vspagent Google Colab Bridge"])

    @router.get("/status")
    async def get_status():
        return {
            "status": internal_colab_client.status,
            "message": internal_colab_client.status_message,
            "gpu_info": internal_colab_client.gpu_info,
            "profileDirectory": internal_colab_client.selected_profile,
            "tools": list(internal_colab_client.tools.keys()),
            "connected": internal_colab_client.status == "connected",
            "colabAvailable": internal_colab_client.status == "connected",
            "recent_logs": list(internal_colab_client.logs)[-25:],
        }

    @router.get("/accounts")
    async def get_accounts():
        return list_chrome_accounts()

    @router.post("/connect")
    async def connect(req: ConnectRequest = ConnectRequest()):
        try:
            return await internal_colab_client.connect_browser(
                profile_directory=req.profileDirectory, force=req.force
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/execute")
    async def execute(req: ExecuteRequest):
        if internal_colab_client.status != "connected":
            raise HTTPException(
                status_code=400,
                detail="Colab GPU runtime is not connected. Call POST /connect first.",
            )
        try:
            return await internal_colab_client.execute_code(
                code=req.code, keep_cell=req.keep_cell, timeout=req.timeout
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/disconnect")
    async def disconnect():
        await internal_colab_client.disconnect()
        return {"status": "disconnected"}

    return router
