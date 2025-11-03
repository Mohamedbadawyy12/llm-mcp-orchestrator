# app/servers/terminal_server.py

import asyncio
from fastapi import HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import json
# --- 1. تم إضافة logger ---
from loguru import logger

from app.servers.base_server import create_mcp_server, McpInfoResponse, ToolInfo
from app.utils.security import run_in_sandbox

# --- 1. Create FastAPI app ---
app = create_mcp_server(server_name="Terminal")

# --- 2. Define Tool Information ---
TERMINAL_TOOL_INFO = ToolInfo(
    name="execute_command",
    description="Executes a sandboxed shell command and streams the output. Only a limited set of safe, read-only commands are allowed (e.g., ls, dir, pwd, cat, echo).",
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command to execute (e.g., 'ls', 'dir'). Must be on the allow-list.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "A list of arguments for the command (e.g., ['-l', '/app']).",
            },
        },
        "required": ["command", "args"],
    },
)

# --- 3. Define MCP Endpoints ---

@app.get("/mcp/info", response_model=McpInfoResponse, tags=["MCP"])
async def info():
    """Provides information about the tools available on this server."""
    return McpInfoResponse(name="Terminal", tools=[TERMINAL_TOOL_INFO])


class RunToolRequest(BaseModel):
    tool_name: str
    params: dict


@app.post("/mcp/run", tags=["MCP"])
async def run_tool(request: RunToolRequest):
    """Runs a tool and streams the output using Server-Sent Events (SSE)."""
    if request.tool_name != "execute_command":
        raise HTTPException(status_code=400, detail=f"Tool '{request.tool_name}' not found.")

    command = request.params.get("command")
    args = request.params.get("args", [])

    async def event_stream():
        """The generator function that yields SSE events."""
        try:
            # Start the subprocess. The security check is inside run_in_sandbox.
            process = await run_in_sandbox(command, args)

            # Asynchronously read stdout and stderr to prevent deadlocks
            async def stream_output(stream, stream_type):
                while not stream.at_eof():
                    line = await stream.readline()
                    if line:
                        try:
                            content = line.decode('utf-8').strip()
                        except UnicodeDecodeError:
                            # إذا فشل utf-8، حاول بترميز ويندوز الافتراضي
                            content = line.decode('cp1252', errors='ignore').strip()
                        
                        yield json.dumps({"type": stream_type, "content": content})

            # Create tasks for streaming stdout and stderr concurrently
            stdout_task = asyncio.create_task(stream_output(process.stdout, "stdout").__anext__())
            stderr_task = asyncio.create_task(stream_output(process.stderr, "stderr").__anext__())

            pending = {stdout_task, stderr_task}
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    try:
                        yield task.result()
                        # Reschedule the task to get the next line
                        if task is stdout_task:
                            stdout_task = asyncio.create_task(stream_output(process.stdout, "stdout").__anext__())
                            pending.add(stdout_task)
                        elif task is stderr_task:
                            stderr_task = asyncio.create_task(stream_output(process.stderr, "stderr").__anext__())
                            pending.add(stderr_task)
                    except StopAsyncIteration:
                        # This stream is finished
                        pass
                    except Exception as e:
                        logger.error(f"Error during stream processing: {e}")
                        yield json.dumps({"type": "error", "content": f"Stream processing error: {str(e)}"})

            exit_code = await process.wait()
            yield json.dumps({"type": "exit_code", "content": exit_code})

        except PermissionError as e:
            # This is raised by run_in_sandbox if the command is not allowed
            # Re-raise as HTTPException to be sent to the client
            raise HTTPException(status_code=403, detail=str(e))
        except Exception as e:
            error_message = json.dumps({"type": "error", "content": f"Failed to execute command: {str(e)}"})
            yield error_message

    return EventSourceResponse(event_stream())