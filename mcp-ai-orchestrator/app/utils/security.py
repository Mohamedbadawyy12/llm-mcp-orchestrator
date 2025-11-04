# app/utils/security.py

import asyncio
from typing import List

# A strict allow-list of safe commands.
# In a real production environment, this should be even more restrictive,
# or better yet, commands should run in an isolated container.
ALLOWED_COMMANDS = {
    "ls",
    "dir",
    "pwd",
    "echo",
    "cat",
    "date",
    "whoami",
    "git",
    "docker", # --- MODIFIED: Add 'docker' to the allowed list ---
    # Add other safe, read-only commands here.
    # Avoid commands that can modify the filesystem or network state like 'rm', 'mv', 'curl', 'wget'.
}


def is_command_safe(command: str) -> bool:
    """
    Checks if the command is in the allowed list.
    This is a very basic security measure.
    """
    if not command:
        return False
    # Split the command to get the base executable
    base_command = command.strip().split()[0]
    return base_command in ALLOWED_COMMANDS


async def run_in_sandbox(command: str, args: List[str]) -> asyncio.subprocess.Process:
    """
    Runs a command securely and asynchronously in a subprocess.

    This function first validates the command against an allow-list and then
    uses asyncio.create_subprocess_shell to run it inside the OS shell.

    Raises:
        PermissionError: If the command is not in the allowed list.
    """
    if not is_command_safe(command):
        raise PermissionError(f"Command '{command}' is not allowed for security reasons.")

    # 1. Combine command and args into a single string for the shell
    full_command_str = f"{command} {' '.join(args)}"

    # 2. Use create_subprocess_shell to run built-in commands like 'dir'
    process = await asyncio.create_subprocess_shell(
        full_command_str, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    return process