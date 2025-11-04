
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Dict, Any


class ToolInfo(BaseModel):
    """Pydantic model for describing a single tool."""
    name: str = Field(..., description="The name of the tool.")
    description: str = Field(..., description="A detailed description of what the tool does.")
    input_schema: Dict[str, Any] = Field(..., description="A JSON schema describing the tool's input parameters.")


class McpInfoResponse(BaseModel):
    """Pydantic model for the /mcp/info endpoint response."""
    name: str = Field(..., description="The name of the server or toolset.")
    tools: List[ToolInfo] = Field(..., description="A list of tools available on this server.")


def create_mcp_server(server_name: str) -> FastAPI:
    """
    Factory function to create a new FastAPI app for an MCP server
    with a default health check endpoint.
    """
    app = FastAPI(
        title=f"MCP Server: {server_name}",
        description=f"An MCP-compliant server providing the '{server_name}' toolset.",
    )

    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}

    return app
