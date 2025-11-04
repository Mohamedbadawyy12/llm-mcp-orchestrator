# app/servers/git_server.py

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
app = create_mcp_server(server_name="Git")

# --- 2. Define Tool Information ---

GIT_CLONE_TOOL = ToolInfo(
    name="git_clone",
    description="Clones a git repository from a URL into a specified directory.",
    input_schema={
        "type": "object",
        "properties": {
            "repo_url": {
                "type": "string",
                "description": "The URL of the git repository (e.g., 'https://github.com/user/repo.git').",
            },
            "path": {
                "type": "string",
                "description": "The local directory to clone into (e.g., 'my_repo').",
            }
        },
        "required": ["repo_url", "path"],
    },
)

GIT_STATUS_TOOL = ToolInfo(
    name="git_status",
    description="Runs 'git status' inside a specified directory to see modified files.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the local git repository (e.g., 'my_repo').",
            }
        },
        "required": ["path"],
    },
)

GIT_ADD_TOOL = ToolInfo(
    name="git_add",
    description="Stages files for a commit. Can add specific files or all changes.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the local git repository (e.g., 'my_repo').",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "A list of files to add (e.g., ['README.md', 'main.py']). Use '[\".\"]' to add all changes.",
            }
        },
        "required": ["path", "files"],
    },
)

GIT_COMMIT_TOOL = ToolInfo(
    name="git_commit",
    description="Commits the staged changes with a message.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path to the local git repository (e.g., 'my_repo').",
            },
            "message": {
                "type": "string",
                "description": "The commit message (e.g., 'feat: add new feature').",
            }
        },
        "required": ["path", "message"],
    },
)


# --- 3. Define MCP Endpoints ---

@app.get("/mcp/info", response_model=McpInfoResponse, tags=["MCP"])
async def info():
    """Provides information about the tools available on this server."""
    return McpInfoResponse(name="Git", tools=[
        GIT_CLONE_TOOL, 
        GIT_STATUS_TOOL,
        GIT_ADD_TOOL,
        GIT_COMMIT_TOOL
    ])


class RunToolRequest(BaseModel):
    tool_name: str
    params: dict

async def _run_git_command(command: str, args: List[str]):
    """
    Helper function to run a git command and return the full output.
    This re-uses the logic from terminal_server to wait for the command to finish.
    """
    # This assumes 'git' is in the system's PATH and allowed in security.py
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
    """Runs a git tool and streams the output."""
    
    async def event_stream():
        """Generator function that runs the tool and yields SSE events."""
        try:
            stdout_str = ""
            stderr_str = ""
            return_code = 1
            
            if request.tool_name == "git_clone":
                repo_url = request.params.get("repo_url")
                path = request.params.get("path")
                if not repo_url or not path:
                    raise HTTPException(status_code=400, detail="Missing repo_url or path")
                
                logger.info(f"Cloning {repo_url} into {path}...")
                stdout_str, stderr_str, return_code = await _run_git_command("git", ["clone", repo_url, path])

            elif request.tool_name == "git_status":
                path = request.params.get("path")
                if not path:
                    raise HTTPException(status_code=400, detail="Missing path")
                
                logger.info(f"Running git status in {path}...")
                stdout_str, stderr_str, return_code = await _run_git_command("git", ["-C", path, "status"])
            
            elif request.tool_name == "git_add":
                path = request.params.get("path")
                files = request.params.get("files", []) # e.g., ['.'] or ['README.md']
                if not path or not files:
                    raise HTTPException(status_code=400, detail="Missing path or files")
                
                logger.info(f"Running git add {files} in {path}...")
                base_args = ["-C", path, "add"]
                full_args = base_args + files
                stdout_str, stderr_str, return_code = await _run_git_command("git", full_args)

            elif request.tool_name == "git_commit":
                path = request.params.get("path")
                message = request.params.get("message")
                if not path or not message:
                    raise HTTPException(status_code=400, detail="Missing path or message")
                
                logger.info(f"Running git commit in {path}...")
                # --- MODIFIED: Add quotes around the message ---
                # This prevents the shell from splitting the message string into multiple arguments
                quoted_message = f'"{message}"'
                stdout_str, stderr_str, return_code = await _run_git_command("git", ["-C", path, "commit", "-m", quoted_message])
                # --- End of modification ---
            
            else:
                raise HTTPException(status_code=400, detail=f"Tool '{request.tool_name}' not found.")

            # Send stdout, stderr, and exit code
            if stdout_str:
                yield json.dumps({"type": "stdout", "content": stdout_str})
            if stderr_str:
                yield json.dumps({"type": "stderr", "content": stderr_str})
            yield json.dumps({"type": "exit_code", "content": return_code})

        except Exception as e:
            logger.error(f"Failed to execute git operation: {e}")
            yield json.dumps({"type": "error", "content": f"Failed to execute: {str(e)}"})

    return EventSourceResponse(event_stream())