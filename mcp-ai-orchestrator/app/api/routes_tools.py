# app/api/routes_tools.py

from fastapi import APIRouter
from typing import List

from app.core.tool_router import tool_router, RegisteredTool

router = APIRouter()

@router.get(
    "/tools",
    response_model=List[RegisteredTool],
    tags=["Tools"],
    summary="List all discovered tools",
    description="Fetches and returns a list of all tools that have been discovered and registered by the orchestrator from all connected MCP servers.",
)
async def list_available_tools():
    """
    Returns a list of all available tools.
    """
    # The tools are stored in a dict, so we return the values.
    return list(tool_router.tools.values())
