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

        # --- 2. تم تعديل هذه الدالة بالكامل بالمنطق الصحيح ---
        def call_model(state: AgentState):
            """Agent node: calls Gemini to decide next action."""
            messages = state.get("messages", [])

            if not messages:
                raise ValueError("No messages found in AgentState — Gemini needs at least one message.")

            logger.debug(f"Calling Gemini with {len(messages)} message(s).")

            system_message = SystemMessage(
                content=(
                    "You are a helpful assistant running on a **Windows operating system**. You have access to a set of tools. "
                    "The user's request is in `HumanMessage`. "
                    "If the request requires a tool (like 'list files'), you must call the tool. **Remember to use Windows commands (e.g., 'dir' instead of 'ls').** "
                    "After you call a tool, you will receive a result. "
                    "Your job is to analyze this result. "
                    "You **must** then respond to the user with a helpful, final text message, either summarizing the tool's result or clearly explaining the error."
                )
            )

            
            last_message = messages[-1]
            messages_for_llm = [system_message] 
            
            if last_message.type == "tool":
                logger.info("Last message was tool result. Cleaning messages for simple LLM.")
                
                for msg in messages:
                    if msg.type == "tool":

                        messages_for_llm.append(HumanMessage(content=f"Tool result: {msg.content}"))
                    else:
                        messages_for_llm.append(msg)
                
                response = self.llm.invoke(messages_for_llm)
                
            else:
                logger.info("Last message was human. Calling LLM with tools for routing.")
                messages_for_llm.extend(messages)
                response = llm_with_tools.invoke(messages_for_llm)

            # --- نهاية الإصلاح ---

            response_content = getattr(response, "content", "")
            if not (response_content and response_content.strip()) and not response.tool_calls:
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
                
                async def _run_async():
                    output_chunks = []
                    async for event in tool_router.run_tool(unique_tool_name=tool_name_for_closure, params=kwargs):
                        output_chunks.append(event)
                    
                    stdout_lines = []
                    stderr_lines = []
                    
                    for event in output_chunks:
                        if not isinstance(event, dict):
                            logger.warning(f"Received non-dict event: {event}")
                            continue
                            
                        event_type = event.get("type")
                        content = event.get("content")
                        
                        if event_type == "stdout":
                            stdout_lines.append(str(content))
                        elif event_type in ("stderr", "error"):
                            stderr_lines.append(str(content))
                    
                    if stderr_lines:
                        return "Tool Error:\n" + "\n".join(stderr_lines)
                    elif stdout_lines:
                        return "Tool Output:\n" + "\n".join(stdout_lines)
                    else:
                        return "Tool ran successfully but produced no output."
                
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