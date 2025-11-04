# app/core/orchestrator.py

import json
import asyncio
from typing import Annotated, Sequence, TypedDict

from langchain_core.tools import StructuredTool
from langchain_core.messages import BaseMessage, ToolMessage, SystemMessage, HumanMessage
from pydantic import create_model, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.core.config import settings
from app.core.tool_router import tool_router


class AgentState(TypedDict):
    """Represents the state of our agent."""
    messages: Sequence[BaseMessage]


class McpOrchestrator:
    """Main orchestrator that manages the agent's lifecycle using LangGraph."""

    def __init__(self, tools):
        self.llm = self._setup_llm()
        self.tools = tools
        self.graph = self._setup_graph()

    def _setup_llm(self) -> ChatGoogleGenerativeAI:
        """Initializes Gemini LLM."""
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set. Please configure it.")

        logger.info("Initializing Gemini LLM...")
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-flash", 
            google_api_key=settings.google_api_key,
            streaming=True,
        )

    def _setup_graph(self):
        """Builds the agent workflow graph."""
        llm_with_tools = self.llm.bind_tools(self.tools)

        def should_continue(state: AgentState) -> str:
            """Determines the next step: call a tool or end."""
            if state["messages"][-1].tool_calls:
                return "tools"
            return END

        def call_model(state: AgentState):
            """Agent node: calls Gemini to decide next action."""
            messages = state.get("messages", [])

            if not messages:
                raise ValueError("No messages found in AgentState — Gemini needs at least one message.")

            logger.debug(f"Calling Gemini with {len(messages)} message(s).")

            system_message = SystemMessage(
                content=(
                    "You are an expert assistant with tools, operating on Windows. "
                    "You will be given a history of messages. You MUST follow these rules: "
                    "1. Analyze the LAST message in the history. "
                    "2. If the LAST message is from the User (`HumanMessage`): Analyze the request. If it matches a tool (like 'list files' -> 'dir'), call the tool. If it's a chat, respond. "
                    "3. If the LAST message is a (`Tool result:`): This is the output of *your* previous action. Your **ONLY** job is to summarize this result for the user and then STOP. "
                    "4. **CRITICAL RULE**: DO NOT call another tool after receiving a `Tool result:`. "
                    "5. **CRITICAL RULE**: DO NOT verify your own work (e.g., DO NOT call `read_file` after `write_file` succeeds). Just report the success of the first tool."
                )
            )

            # --- This is the fix that worked last time (cleaning history) ---
            logger.info("Cleaning message history for LLM consumption...")
            messages_for_llm = [system_message] # Start the new message list
            for msg in messages:
                if msg.type == "tool":
                    # Convert the tool message to a HumanMessage
                    messages_for_llm.append(HumanMessage(content=f"Tool result: {msg.content}"))
                else:
                    # Keep HumanMessage and AIMessage as they are
                    messages_for_llm.append(msg)
            
            # We always use the tool-bound model
            logger.info("Calling LLM with tools to decide next step or summarize.")
            response = llm_with_tools.invoke(messages_for_llm)
            # --- End of fix ---

            # Check for empty/blank content
            response_content = getattr(response, "content", "")
            is_content_blank = False
            if isinstance(response_content, str):
                is_content_blank = not response_content.strip()
            elif isinstance(response_content, list):
                is_content_blank = not bool(response_content)
            else:
                is_content_blank = not bool(response_content)

            if is_content_blank and not response.tool_calls:
                logger.error("Gemini returned empty or blank content and no tool calls.")
                raise ValueError("Gemini returned empty content.")

            logger.info("✅ Gemini responded successfully.")
            return {"messages": [response]}

        # Build graph
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue)
        workflow.add_edge("tools", "agent")

        logger.info("Compiling LangGraph...")
        return workflow.compile()


async def create_langchain_tools_from_router():
    """
    Dynamically creates LangChain-compatible tools from the discovered tools
    in the ToolRouter.
    """
    logger.info("Creating LangChain tools from discovered MCP tools...")
    langchain_tools = []

    type_mapping = {
        "string": (str, ...),
        "array": (list, ...),
        "number": (float, ...),
        "integer": (int, ...),
        "boolean": (bool, ...),
        "object": (dict, ...),
    }

    for unique_name, registered_tool in tool_router.tools.items():
        gemini_compatible_name = unique_name.replace('/', '_')

        fields = {}
        for prop, details in registered_tool.input_schema.get("properties", {}).items():
            prop_type = details.get("type")
            field_description = details.get("description")

            if prop_type == "array":
                item_type_str = details.get("items", {}).get("type", "string")
                python_item_type = type_mapping.get(item_type_str, (str, ...))[0]
                fields[prop] = (list[python_item_type], Field(description=field_description, default=...))
            else:
                python_type = type_mapping.get(prop_type, (str, ...))[0]
                fields[prop] = (python_type, Field(description=field_description, default=...))

        args_model = create_model(
            f"{gemini_compatible_name.replace('_', ' ').title().replace(' ', '')}Input",
            **fields
        )

        def create_sync_func(tool_name_for_closure: str):
            def tool_func(**kwargs):
                logger.info(f"Agent is calling tool: {tool_name_for_closure} with args: {kwargs}")
                
                # This function is sync, but the tool_router is async.
                # We use asyncio.run() to bridge the gap.
                async def _run_async():
                    output_chunks = []
                    async for event in tool_router.run_tool(unique_tool_name=tool_name_for_closure, params=kwargs):
                        output_chunks.append(event)
                    
                    # --- MODIFIED: Parse events based on exit_code ---
                    stdout_lines = []
                    stderr_lines = []
                    exit_code = 1 # Assume failure unless we see exit_code 0

                    for event in output_chunks:
                        if not isinstance(event, dict):
                            logger.warning(f"Received non-dict event: {event}")
                            continue
                            
                        event_type = event.get("type")
                        content = event.get("content")
                        
                        if event_type == "stdout":
                            stdout_lines.append(str(content))
                        elif event_type == "stderr": # git clone logs progress to stderr
                            stderr_lines.append(str(content))
                        elif event_type == "error": # A custom error from our server
                            stderr_lines.append(str(content))
                        elif event_type == "exit_code":
                            try:
                                exit_code = int(content)
                            except (ValueError, TypeError):
                                logger.error(f"Invalid exit_code received: {content}")
                                exit_code = 1
                    
                    # Now, format the output based on the exit_code
                    stdout_full = "\n".join(stdout_lines)
                    stderr_full = "\n".join(stderr_lines)

                    if exit_code == 0:
                        # SUCCESS!
                        if stdout_full:
                            return f"Tool Output (stdout):\n{stdout_full}"
                        elif stderr_full:
                            # This handles 'git clone' progress messages
                            return f"Tool Output (stderr, command succeeded):\n{stderr_full}"
                        else:
                            return "Tool ran successfully with no output."
                    else:
                        # FAILURE!
                        if stderr_full:
                            return f"Tool Error (exit code {exit_code}):\n{stderr_full}"
                        elif stdout_full:
                            return f"Tool Error (exit code {exit_code}, stderr was empty):\n{stdout_full}"
                        else:
                            return f"Tool Error (exit code {exit_code}). No output."
                    # --- End of modification ---

                return asyncio.run(_run_async())
            
            return tool_func

        langchain_tools.append(
            StructuredTool.from_function(
                name=gemini_compatible_name,
                description=registered_tool.description,
                func=create_sync_func(unique_name), 
                args_schema=args_model
            )
        )

    logger.info(f"Created {len(langchain_tools)} LangChain tools.")
    return langchain_tools


# Global agent graph (initialized at startup)
agent_graph = None