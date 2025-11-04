# app/servers/docker_server.py

import json
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from loguru import logger
from typing import List

# Import the sandbox runner from the terminal server's utils
from app.utils.security import run_in_sandbox
from app.servers.base_server import create_mcp_server, McpInfoResponse, ToolInfo

# --- 1. Create FastAPI app ---
app = create_mcp_server(server_name="Docker")

# --- 2. Define Tool Information ---

DOCKER_BUILD_TOOL = ToolInfo(
    name="docker_build",
    description="Builds a Docker image from a Dockerfile in a specified path.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The directory containing the Dockerfile (e.g., '.').",
            },
            "tag": {
                "type": "string",
                "description": "The tag for the image (e.g., 'my-app:latest').",
            }
        },
        "required": ["path", "tag"],
    },
)

DOCKER_PS_TOOL = ToolInfo(
    name="docker_ps",
    description="Lists all Docker containers (running and stopped).",
    input_schema={"type": "object", "properties": {}},
)

DOCKER_RUN_TOOL = ToolInfo(
    name="docker_run",
    description="Runs a Docker image in detached mode.",
    input_schema={
        "type": "object",
        "properties": {
            "image_tag": {
                "type": "string",
                "description": "The tag of the image to run (e.g., 'my-app:latest').",
            }
        },
        "required": ["image_tag"],
    },
)

# --- 3. Define MCP Endpoints ---

@app.get("/mcp/info", response_model=McpInfoResponse, tags=["MCP"])
async def info():
    """Provides information about the tools available on this server."""
    return McpInfoResponse(name="Docker", tools=[
        DOCKER_BUILD_TOOL,
        DOCKER_PS_TOOL,
        DOCKER_RUN_TOOL
    ])


class RunToolRequest(BaseModel):
    tool_name: str
    params: dict

async def _run_docker_command(command: str, args: List[str]):
    """
    Helper function to run a docker command and return the full output.
    """
    process = await run_in_sandbox(command, args)
    stdout_bytes, stderr_bytes = await process.communicate()
    
    stdout_str = ""
    stderr_str = ""
    
    if stdout_bytes:
        try:
            stdout_str = stdout_bytes.decode('utf-8').strip()
        except UnicodeDecodeError:
            stdout_str = stdout_bytes.decode('cp1252', errors='ignore').strip()

    if stderr_bytes:
        try:
            stderr_str = stderr_bytes.decode('utf-8').strip()
        except UnicodeDecodeError:
            stderr_str = stderr_bytes.decode('cp1252', errors='ignore').strip()
            
    return stdout_str, stderr_str, process.returncode

@app.post("/mcp/run", tags=["MCP"])
async def run_tool(request: RunToolRequest):
    """Runs a docker tool and streams the output."""
    
    async def event_stream():
        """Generator function that runs the tool and yields SSE events."""
        try:
            stdout_str = ""
            stderr_str = ""
            return_code = 1
            
            if request.tool_name == "docker_build":
                path = request.params.get("path", ".")
                tag = request.params.get("tag")
                if not tag:
                    raise HTTPException(status_code=400, detail="Missing 'tag' for docker_build")
                
                logger.info(f"Building Docker image at {path} with tag {tag}...")
                # Command: docker build -t {tag} {path}
                stdout_str, stderr_str, return_code = await _run_docker_command("docker", ["build", "-t", tag, path])

            elif request.tool_name == "docker_ps":
                logger.info("Running docker ps -a...")
                # Command: docker ps -a
                stdout_str, stderr_str, return_code = await _run_docker_command("docker", ["ps", "-a"])
            
            elif request.tool_name == "docker_run":
                image_tag = request.params.get("image_tag")
                if not image_tag:
                    raise HTTPException(status_code=400, detail="Missing 'image_tag' for docker_run")
                
                logger.info(f"Running Docker image {image_tag}...")
                # Command: docker run -d {image_tag}
                stdout_str, stderr_str, return_code = await _run_docker_command("docker", ["run", "-d", image_tag])
            
            else:
                raise HTTPException(status_code=400, detail=f"Tool '{request.tool_name}' not found.")

            # Send stdout, stderr, and exit code
            if stdout_str:
                yield json.dumps({"type": "stdout", "content": stdout_str})
            if stderr_str:
                yield json.dumps({"type": "stderr", "content": stderr_str})
            yield json.dumps({"type": "exit_code", "content": return_code})

        except Exception as e:
            logger.error(f"Failed to execute docker operation: {e}")
            yield json.dumps({"type": "error", "content": f"Failed to execute: {str(e)}"})

    return EventSourceResponse(event_stream())