# app/clients/mcp_http_client.py

import json
from typing import AsyncGenerator, Dict, Any

import httpx
from httpx_sse import aconnect_sse
from loguru import logger

from app.servers.base_server import McpInfoResponse


class MCPHttpClient:
    """
    An asynchronous HTTP client for interacting with MCP-compliant servers.
    """

    def __init__(self, server_url: str, timeout: int = 30):
        """
        Initializes the client for a specific MCP server.

        Args:
            server_url: The base URL of the MCP server (e.g., http://127.0.0.1:8001).
            timeout: The timeout in seconds for HTTP requests.
        """
        self.base_url = server_url
        self.timeout = timeout
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def get_info(self) -> McpInfoResponse | None:
        """
        Fetches the /mcp/info endpoint to discover the tools available on the server.

        Returns:
            An McpInfoResponse object describing the server's tools, or None if an error occurs.
        """
        try:
            logger.info(f"Fetching tool info from {self.base_url}/mcp/info")
            response = await self.client.get("/mcp/info")
            response.raise_for_status()  # Raise an exception for 4xx or 5xx status codes
            return McpInfoResponse(**response.json())
        except httpx.RequestError as e:
            logger.error(f"HTTP request error while fetching info from {self.base_url}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching info from {self.base_url}: {e}")
        return None

    async def run_tool(
        self, tool_name: str, params: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes a tool on the MCP server and streams the results via SSE.

        Args:
            tool_name: The name of the tool to run.
            params: A dictionary of parameters for the tool.

        Yields:
            A dictionary for each event received from the server (e.g., stdout, stderr, exit_code).
        """
        request_body = {"tool_name": tool_name, "params": params}
        logger.info(f"Running tool '{tool_name}' on {self.base_url} with params: {params}")
        try:
            async with aconnect_sse(
                self.client, "POST", f"{self.base_url}/mcp/run", json=request_body
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    try:
                        # Each event's data is a JSON string
                        yield json.loads(sse.data)
                    except json.JSONDecodeError:
                        logger.warning(f"Received non-JSON SSE data: {sse.data}")
        except httpx.RequestError as e:
            logger.error(f"HTTP error while running tool '{tool_name}' on {self.base_url}: {e}")
            yield {"type": "error", "content": f"Failed to connect to server: {e}"}
        except Exception as e:
            logger.error(f"An unexpected error occurred while running tool '{tool_name}': {e}")
            yield {"type": "error", "content": f"An unexpected error occurred: {e}"}