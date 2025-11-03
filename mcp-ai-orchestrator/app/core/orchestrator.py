# app/core/orchestrator.py

import json
from typing import Annotated, Sequence, TypedDict

from langchain_core.tools import StructuredTool
from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import create_model, BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.core.config import settings
from app.core.tool_router import tool_router


class AgentState(TypedDict):
    """
    Represents the state of our agent.
    """
    messages: Sequence[BaseMessage]


class McpOrchestrator:
    """
    The main orchestrator class that manages the agent's lifecycle using LangGraph.
    """

    def __init__(self, tools):
        self.llm = self._setup_llm()
        self.tools = tools
        self.graph = self._setup_graph()

    def _setup_llm(self) -> ChatGoogleGenerativeAI:
        """Initializes the Gemini LLM."""
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY is not set. Please configure it in your environment or settings.")
        
        logger.info("Initializing Gemini LLM...")
        return ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
            google_api_key=settings.google_api_key,
            convert_system_message_to_human=True, # Gemini doesn't have a "system" role
            streaming=True,
        )

    def _setup_graph(self):
        """Builds the agent graph using LangGraph."""
        llm_with_tools = self.llm.bind_tools(self.tools)

        def should_continue(state: AgentState) -> str:
            """Determines the next step: call a tool or end the conversation."""
            if state["messages"][-1].tool_calls:
                return "tools"
            return END

        def call_model(state: AgentState):
            """The 'agent' node: calls the LLM to decide the next action."""
            response = llm_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        # Define the graph
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # Define the edges
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

    # Type mapping from JSON Schema to Python types for Pydantic model creation
    type_mapping = {
        "string": (str, ...),
        "array": (list, ...),
        "number": (float, ...),
        "integer": (int, ...),
        "boolean": (bool, ...),
        "object": (dict, ...),
    }

    for unique_name, registered_tool in tool_router.tools.items():
        # Gemini requires tool names to not contain '/', so we replace it.
        gemini_compatible_name = unique_name.replace('/', '_')

        # Dynamically create a Pydantic model from the tool's JSON schema
        fields = {}
        for prop, details in registered_tool.input_schema.get("properties", {}).items():
            prop_type = details.get("type")
            field_description = details.get("description")

            if prop_type == "array":
                # Handle array types by specifying the item type
                item_type_str = details.get("items", {}).get("type", "string")
                python_item_type = type_mapping.get(item_type_str, (str, ...))[0]
                fields[prop] = (list[python_item_type], Field(description=field_description, default=...))
            else:
                # Handle simple types
                python_type = type_mapping.get(prop_type, (str, ...))[0]
                fields[prop] = (python_type, Field(description=field_description, default=...))

        args_model = create_model(f"{gemini_compatible_name.replace('_', ' ').title().replace(' ', '')}Input", **fields)

        # Use a closure to capture the tool's unique name for the async function
        def create_async_func(tool_name_for_closure: str):
            async def tool_func(**kwargs):
                logger.info(f"Agent is calling tool: {tool_name_for_closure} with args: {kwargs}")
                output_chunks = []
                # We still use the original unique_name to talk to our tool_router
                async for event in tool_router.run_tool(unique_tool_name=unique_name, params=kwargs):
                    output_chunks.append(event)
                return json.dumps(output_chunks, indent=2)
            return tool_func

        langchain_tools.append(StructuredTool.from_function(
            name=gemini_compatible_name,
            description=registered_tool.description,
            func=create_async_func(unique_name),
            args_schema=args_model
        ))

    logger.info(f"Created {len(langchain_tools)} LangChain tools.")
    return langchain_tools

# This will be populated at startup
agent_graph = None
