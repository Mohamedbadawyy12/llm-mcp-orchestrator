
#  AI Orchestrator



## Overview

The **AI Orchestrator** is a sophisticated, enterprise-ready platform for building and deploying tool-augmented Generative AI agents. This project moves beyond simple chatbot wrappers by implementing a robust, containerized microservice architecture. At its core, a central orchestrator, powered by **LangGraph** and **Google's Gemini model**, intelligently routes tasks to a suite of decoupled, specialized microservices.

These "tool servers" provide the AI agent with a secure bridge to real-world capabilities, including:

  * **File System** access (reading and writing files)
  * **Terminal** execution (running sandboxed shell commands)
  * **Git Operations** (cloning repositories, checking status)
  * **Docker Management** (building images, listing containers)

This decoupled design ensures the system is not only highly **scalable** and **extensible** but also maintains a strong security posture by isolating high-risk operations.

## Core Features

  * **Microservice Architecture:** The entire platform runs as a set of coordinated Docker containers, with the main orchestrator communicating with distinct tool servers.
  * **Dynamic Tool Discovery:** At startup, the orchestrator queries all configured microservices to dynamically build its library of available tools. This makes adding new capabilities as simple as deploying a new service.
  * **Stateful Agentic Workflows:** Leverages **LangGraph** to create a state-driven agent. This allows the AI to perform complex, multi-step tasks, call tools, and analyze their outputs before responding to the user.
  * **Real-time Asynchronous Streaming:** All communication, from the user to the agent and from the agent to the tools, is fully asynchronous and uses **Server-Sent Events (SSE)** for real-time output streaming.
  * **Production-Ready Configuration:** Implements `pydantic-settings` to manage configuration from `.env` files, YAML, and environment variables, providing flexibility for development and production deployments.
  * **Centralized Logging:** Uses `Loguru` to intercept all application and Uvicorn logs, providing consistent, colorized, and well-structured logging output.

## Architecture Deep-Dive

The system is composed of five primary services defined in the `docker-compose.yml` file:

1.  **`orchestrator` (The Brain)**

      * **Stack:** FastAPI, LangGraph, Google Gemini.
      * **Role:** Exposes the main `/chat/stream` API endpoint. It receives user requests, manages the conversation state using `AgentState`, and orchestrates the flow. It decides when to call a tool and which tool to use.
      * **Key Components:**
          * `ToolRouter`: Discovers and registers tools from other services.
          * `Orchestrator`: Defines the LangGraph agent workflow.
          * `HttpClient`: An asynchronous client for communicating with the tool servers.

2.  **`terminal_server`**

      * **Stack:** FastAPI, SSE.
      * **Role:** Provides a single tool: `execute_command`. It runs commands within a secure sandbox, streaming `stdout`, `stderr`, and the final `exit_code` back to the orchestrator via SSE.

3.  **`file_system_server`**

      * **Stack:** FastAPI, SSE.
      * **Role:** Provides `read_file` and `write_file` tools. It performs file operations on the mounted workspace volume and streams the result or success message.

4.  **`git_server`**

      * **Stack:** FastAPI, SSE.
      * **Role:** Exposes Git functionalities like `git_clone`, `git_status`, `git_add`, and `git_commit`.

5.  **`docker_server`**

      * **Stack:** FastAPI, SSE.
      * **Role:** Provides tools to interact with the host's Docker daemon (via a mounted socket), allowing the agent to `docker_build`, `docker_ps`, and `docker_run`.

## How It Works: The Request Lifecycle

1.  A user sends a request (e.g., "Write 'hello world' to a file named 'hello.txt'") to the `orchestrator`'s `/chat/stream` endpoint.
2.  The orchestrator adds the `HumanMessage` to the `AgentState` for the user's `thread_id`.
3.  **LangGraph**'s `call_model` node is triggered. It invokes the Gemini LLM with the current conversation history.
4.  The LLM analyzes the request and determines that it must use a tool. It responds with a tool call: `file_system_server/write_file` with params `{"path": "hello.txt", "content": "hello world"}`.
5.  The graph's `should_continue` edge routes the flow to the `tools` node.
6.  The `ToolRouter` receives the tool call, identifies that `file_system_server` is responsible, and uses its `MCPHttpClient` to make an async POST request to the `mcp_file_system_server`'s `/mcp/run` endpoint.
7.  The `mcp_file_system_server` executes the `write_file` logic, creates `hello.txt` on the disk, and streams an SSE response: `{"type": "stdout", "content": "Successfully wrote 11 characters..."}` followed by `{"type": "exit_code", "content": 0}`.
8.  The orchestrator's `ToolNode` collects this stream and packages the result into a `ToolMessage`.
9.  The graph loops back to the `agent` node. The LLM receives the `ToolMessage` (e.g., "Tool result: Successfully wrote..."), formulates a user-friendly summary, and streams the final `AIMessage` (e.g., "I have successfully created the file `hello.txt` with your content.") back to the user.

## Technology Stack

  * **Backend:** Python 3.11, FastAPI, Uvicorn
  * **AI Orchestration:** LangChain, LangGraph
  * **Generative AI:** Google Gemini (via `langchain-google-genai`)
  * **Containerization:** Docker, Docker Compose
  * **Async & Streaming:** `asyncio`, `httpx`, `sse-starlette`, `httpx-sse`
  * **Configuration:** Pydantic, Pydantic-Settings, PyYAML
  * **Logging:** Loguru

## Getting Started

### Prerequisites

  * Docker and Docker Compose
  * Python 3.11 (for local type-checking, though not strictly required if only using Docker)
  * A Google Gemini API Key

### Installation & Launch

1.  **Clone the Repository**

    ```bash
    git clone <your-repo-url>
    cd ai-orchestrator
    ```

2.  **Create Environment File**
    This project uses a `.env` file for secrets.

    ```bash
    cp .env.example .env
    ```

    Now, edit `.env` and add your `GOOGLE_API_KEY`:

    ```
    GOOGLE_API_KEY="your_gemini_api_key_here"
    ```

3.  **Build and Run with Docker Compose**
    This is the simplest way to run the entire microservice ecosystem.

    ```bash
    docker-compose up --build
    ```

    This command will:

      * Build the shared Docker image.
      * Start all five services (`orchestrator`, `terminal_server`, etc.).
      * Mount the local code directory into each container for live-reloading.

4.  **Access the API**
    The main orchestrator is now running and accessible:

      * **API Root:** `http://localhost:8000/`
      * **Swagger Docs:** `http://localhost:8000/docs`
      * **List Discovered Tools:** `http://localhost:8000/tools`
      * **Chat Endpoint:** `http://localhost:8000/chat/stream` (Use a tool like Postman or a custom client to interact with this SSE endpoint).
