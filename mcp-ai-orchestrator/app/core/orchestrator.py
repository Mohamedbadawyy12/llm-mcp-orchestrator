# app/core/orchestrator.py

import json
from typing import Annotated, Sequence, TypedDict

from langchain_core.tools import StructuredTool
from langchain_core.messages import BaseMessage, ToolMessage
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
            model="gemini-2.5-pro",
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

            # Always include system context (Gemini expects it)
            system_message = {
                "role": "system",
                "content": (
                    "You are an intelligent MCP Orchestrator agent. "
                    "You analyze user messages, decide if any registered tool should be called, "
                    "and return helpful, structured responses. "
                    "If a tool is needed, include its call in the output."
                ),
            }

            # Convert messages to Gemini-compatible dicts
            gemini_messages = [system_message]
            for msg in messages:
                role = "user" if msg.type == "human" else "assistant"
                gemini_messages.append({"role": role, "content": msg.content})

            response = self.llm.invoke(gemini_messages)

            if not getattr(response, "content", None):
                logger.error("Gemini returned empty content — invalid message formatting.")
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

        def create_async_func(tool_name_for_closure: str):
            async def tool_func(**kwargs):
                logger.info(f"Agent is calling tool: {tool_name_for_closure} with args: {kwargs}")
                output_chunks = []
                async for event in tool_router.run_tool(unique_tool_name=tool_name_for_closure, params=kwargs):
                    output_chunks.append(event)
                return json.dumps(output_chunks, indent=2)
            return tool_func

        # ✅ FIX: use func= instead of coro=
        langchain_tools.append(
            StructuredTool.from_function(
                name=gemini_compatible_name,
                description=registered_tool.description,
                func=create_async_func(unique_name),
                args_schema=args_model
            )
        )

    logger.info(f"Created {len(langchain_tools)} LangChain tools.")
    return langchain_tools


# Global agent graph (initialized at startup)
agent_graph = None
