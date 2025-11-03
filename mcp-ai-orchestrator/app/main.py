# app/main.py
import time

from fastapi import FastAPI, Request
from loguru import logger

from app.core.config import settings # Import the settings instance
from app.core.logger import setup_logging
from app.api import routes_tools, routes_chat 
from app.core import orchestrator as orchestrator_module
from app.core.tool_router import tool_router

# Create a FastAPI app instance
app = FastAPI(
    title=settings.project_name, # Use the project name from settings
    description="A Multi-Agent Platform using MCP, LangChain, and Gemini.",
    version="0.1.0",
    # # Disable docs in production if needed, based on debug flag
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Include API routers
app.include_router(routes_tools.router)
app.include_router(routes_chat.router)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    FastAPI middleware to log every incoming request.
    """
    start_time = time.time()
    logger.info(f"Request: {request.method} {request.url.path}")
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = f"{process_time:.2f}ms"
    logger.info(
        f"Response: {response.status_code} | Path: {request.url.path} | Duration: {formatted_process_time}"
    )
    return response

@app.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint to check if the server is running.
    """
    return {
        "status": "ok",
        "message": f"Welcome to {settings.project_name}!", # Use setting here
        "debug_mode": settings.debug
    }

@app.on_event("startup")
async def startup_event():
    setup_logging()
    logger.info(f"Starting up {settings.project_name}...")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"Debug mode: {'On' if settings.debug else 'Off'}")
    
    # Discover and register all tools from MCP servers
    await tool_router.discover_tools()

    # Now that tools are discovered, create the LangChain tools and the orchestrator
    try:
        langchain_tools = await orchestrator_module.create_langchain_tools_from_router()
        if langchain_tools:
            orchestrator_instance = orchestrator_module.McpOrchestrator(tools=langchain_tools)
            orchestrator_module.agent_graph = orchestrator_instance.graph
            logger.success("Orchestrator and agent graph initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"Shutting down {settings.project_name}...")
