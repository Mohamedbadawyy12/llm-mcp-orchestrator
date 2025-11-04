# app/servers/file_server.py

import json
import os
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from loguru import logger
from typing import List, Dict, Any

from app.servers.base_server import create_mcp_server, McpInfoResponse, ToolInfo

# --- 1. Create FastAPI app ---
app = create_mcp_server(server_name="FileSystem")

# --- 2. Define Tool Information ---

READ_FILE_TOOL = ToolInfo(
    name="read_file",
    description="Reads the entire content of a specified text file from the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The relative path to the file (e.g., 'app/main.py' or 'requirements.txt').",
            }
        },
        "required": ["path"],
    },
)

WRITE_FILE_TOOL = ToolInfo(
    name="write_file",
    description="Writes or overwrites content to a specified text file in the workspace.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The relative path to the file (e.g., 'notes.txt').",
            },
            "content": {
                "type": "string",
                "description": "The full text content to write into the file.",
            },
        },
        "required": ["path", "content"],
    },
)

# --- 3. Define MCP Endpoints ---

@app.get("/mcp/info", response_model=McpInfoResponse, tags=["MCP"])
async def info():
    """Provides information about the tools available on this server."""
    return McpInfoResponse(name="FileSystem", tools=[READ_FILE_TOOL, WRITE_FILE_TOOL])


class RunToolRequest(BaseModel):
    tool_name: str
    params: dict


@app.post("/mcp/run", tags=["MCP"])
async def run_tool(request: RunToolRequest):
    """Runs a file system tool and streams the output."""
    
    # Simple security: ensure path is relative and prevent traversal
    path = request.params.get("path")
    if not path or ".." in path or os.path.isabs(path):
        raise HTTPException(status_code=400, detail=f"Invalid or unsafe path specified: {path}")

    async def event_stream():
        """Generator function that runs the tool and yields SSE events."""
        try:
            if request.tool_name == "read_file":
                logger.info(f"Reading file: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Yield the content as 'stdout' for consistency with terminal_server
                yield json.dumps({"type": "stdout", "content": content})

            elif request.tool_name == "write_file":
                content = request.params.get("content", "")
                logger.info(f"Writing to file: {path}")
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                yield json.dumps({"type": "stdout", "content": f"Successfully wrote {len(content)} characters to {path}"})
            
            else:
                raise HTTPException(status_code=400, detail=f"Tool '{request.tool_name}' not found.")

            # Send a final exit code
            yield json.dumps({"type": "exit_code", "content": 0})

        except FileNotFoundError:
            logger.warning(f"File not found: {path}")
            yield json.dumps({"type": "error", "content": f"File not found: {path}"})
        except Exception as e:
            logger.error(f"Failed to execute file operation: {e}")
            yield json.dumps({"type": "error", "content": f"Failed to execute: {str(e)}"})

    return EventSourceResponse(event_stream())