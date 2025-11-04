# app/core/tool_router.py

import json
from typing import Dict, Any, AsyncGenerator

from loguru import logger

from app.clients.mcp_http_client import MCPHttpClient
from app.core.config import settings, BASE_DIR
from app.servers.base_server import ToolInfo


class RegisteredTool(ToolInfo):
    """
    Represents a tool that has been discovered and registered with the router.
    It extends the basic ToolInfo with the server it belongs to.
    """
    server_name: str
    unique_name: str


class ToolRouter:
    """
    Discovers, registers, and routes requests to all available tools
    from the configured MCP servers.
    """

    def __init__(self):
        self.clients: Dict[str, MCPHttpClient] = {}
        self.tools: Dict[str, RegisteredTool] = {}

    async def discover_tools(self):
        """
        Reads the server configuration, connects to each server,
        and registers its tools. This should be called at application startup.
        """
        logger.info("Starting tool discovery...")
        config_path = BASE_DIR / settings.mcp_servers_config_path

        if not config_path.exists():
            logger.error(f"Servers config file not found at: {config_path}")
            return

        with open(config_path, "r") as f:
            servers = json.load(f)

        for server_config in servers:
            server_name = server_config.get("name")
            server_url = server_config.get("url")
            is_enabled = server_config.get("enabled", False)

            if not is_enabled:
                logger.warning(f"Skipping disabled server: {server_name}")
                continue

            if not server_name or not server_url:
                logger.error(f"Invalid server config entry: {server_config}")
                continue
            
            client = MCPHttpClient(server_url=server_url)
            self.clients[server_name] = client

            # discovery_client سيتم استخدامه فقط لهذه الدالة (داخل اللوب الرئيسي)
            discovery_client = MCPHttpClient(server_url=server_url)
            info = await discovery_client.get_info()
            # --- نهاية التعديل ---
            
            if info and info.tools:
                for tool_info in info.tools:
                    unique_name = f"{server_name}/{tool_info.name}"
                    self.tools[unique_name] = RegisteredTool(
                        **tool_info.model_dump(),
                        server_name=server_name,
                        unique_name=unique_name
                    )
                    logger.success(f"Discovered and registered tool: {unique_name}")
            else:
                logger.error(f"Failed to discover tools from server: {server_name} at {server_url}")

        logger.info(f"Tool discovery complete. Total tools registered: {len(self.tools)}")

    async def run_tool(
        self, unique_tool_name: str, params: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Finds the appropriate server for a tool and executes it.
        """
        if unique_tool_name not in self.tools:
            error_msg = f"Tool '{unique_tool_name}' not found."
            logger.error(error_msg)
            yield {"type": "error", "content": error_msg}
            return

        registered_tool = self.tools[unique_tool_name]
        server_name = registered_tool.server_name
        tool_name = registered_tool.name
        
        # --- تم التعديل هنا ---
        # احصل على العميل (الذي يحتوي فقط على الـ URL)
        client = self.clients[server_name]
        # client.run_tool سيقوم بإنشاء عميل httpx جديد بنفسه
        async for event in client.run_tool(tool_name=tool_name, params=params):
            yield event
        # --- نهاية التعديل ---

# Create a single, global instance of the ToolRouter
tool_router = ToolRouter()