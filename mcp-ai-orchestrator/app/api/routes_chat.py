# app/api/routes_chat.py

import json
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from loguru import logger

from app.core import orchestrator

router = APIRouter()

class ChatRequest(BaseModel):
    """Request model for chat streaming."""
    message: str
    thread_id: str  # used later for conversation tracking


@router.post("/chat/stream")
async def chat_stream(chat_request: ChatRequest):
    """Streams agent responses using Server-Sent Events (SSE)."""
    if not orchestrator.agent_graph:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized. Check startup logs.")

    logger.info(f"Received chat request: '{chat_request.message}' [thread={chat_request.thread_id}]")

    async def event_stream():
        try:
            graph_input = {"messages": [HumanMessage(content=chat_request.message)]}

            async for step in orchestrator.agent_graph.astream_events(graph_input, version="v1"):
                event_data = {
                    "event": step["event"],
                    "name": step["name"],
                    "data": {}
                }

                if step["event"] == "on_chain_end":
                    data = step["data"].get("output")
                    if isinstance(data, dict) and "messages" in data:
                        messages = data["messages"]
                        for msg in messages:
                            if isinstance(msg, AIMessage):
                                event_data["data"]["type"] = "ai_message"
                                event_data["data"]["content"] = msg.content
                                event_data["data"]["tool_calls"] = msg.tool_calls
                            elif isinstance(msg, ToolMessage):
                                event_data["data"]["type"] = "tool_result"
                                event_data["data"]["content"] = msg.content
                                event_data["data"]["tool_call_id"] = msg.tool_call_id

                yield json.dumps(event_data)

        except Exception as e:
            logger.error(f"Error during agent execution: {e}")
            yield json.dumps({"error": str(e)})

    return EventSourceResponse(event_stream())
