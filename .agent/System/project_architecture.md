# Project Architecture – Merak Agent ChatKit Backend

## Overview
- **Goal:** Provide a FastAPI backend that exposes Merak’s hiring agent over ChatKit so web clients can orchestrate multi-turn conversations and trigger the `search_agents` tool when a brief is ready.
- **Key Capabilities:**
  - Collect hiring requirements through the Merak agent prompt (`MERAK_AGENT_INSTRUCTIONS`).
  - Persist thread history during a session using an in-memory `MemoryStore` implementation compatible with ChatKit.
  - Stream assistant/tool events to clients via `ChatKitServer.process` and SSE responses.

## High-Level Architecture
- **FastAPI layer (`app/main.py`):** Hosts `/chatkit` for ChatKit payloads and `/health` for monitoring. Requests are passed straight to the server’s `process` method; streaming responses are surfaced as `text/event-stream`, and non-streaming responses are returned as JSON.
- **Chat server (`app/chat.py`):** Implements `MerakAgentServer`, a `ChatKitServer` subclass that:
  - Wraps a single `Agent` instance (`self.assistant`) configured with the Merak instructions and the `search_agents` tool.
  - Uses `MerakAgentContext` to carry thread metadata plus the in-memory store into the Agents SDK runner.
  - Loads recent thread history (up to 12 relevant items) and converts it to agent input via `ThreadItemConverter.to_agent_input`, falling back to raw text only when conversion fails.
  - Streams `ThreadStreamEvent` instances produced by `stream_agent_response` back to FastAPI.
- **Agent + tool layer (`app/merak_agent_tool.py`):** Defines the Merak orchestrator agent and its `search_agents` tool:
  - Tool input is validated with a Pydantic model (`FunctionArgs`).
  - Queries OpenAI’s vector store (`client.vector_stores.search`) using filters derived from the gathered facets.
  - Returns results as JSON via `ToolOutputText` so the agent can summarise matches for the user.
- **State management (`app/memory_store.py`):** Implements ChatKit’s `Store` interface in memory. Threads and items are stored in Python dictionaries/lists—suitable for local development and testing, but not persistent across restarts.

## Project Structure
```
app/
├── chat.py              # ChatKit server subclass + agent context
├── constants.py         # Shared instructions and model ids
├── core/settings.py     # Pydantic settings (OpenAI API key, vector store id)
├── main.py              # FastAPI application and route wiring
├── memory_store.py      # In-memory Store implementation for ChatKit
└── merak_agent_tool.py  # Merak agent definition and search tool implementation
.agent/                  # Documentation hub (system, SOP, task plans)
requirements.txt         # Runtime dependencies (FastAPI, ChatKit, OpenAI Agents)
```

## Tech Stack
- **Language:** Python 3.12
- **Web framework:** FastAPI + Starlette
- **Agent SDKs:** `openai-agents`, `openai-chatkit`
- **Streaming transport:** Server-Sent Events exposed by ChatKit’s `StreamingResult`
- **Vector search:** OpenAI Vector Store accessed via the official `openai` client
- **State:** In-memory `MemoryStore` (non-persistent); no relational database

## Request Flow
1. Client sends ChatKit payloads to `POST /chatkit` (e.g., `threads.create`, `threads.add_user_message`).
2. FastAPI forwards the raw body to `MerakAgentServer.process`, supplying `{ "request": Request }` as context.
3. `ChatKitServer.process` validates the payload and, for streaming requests, invokes `MerakAgentServer.respond`.
4. `respond` builds a `MerakAgentContext`, coalesces recent thread history, converts it via `ThreadItemConverter.to_agent_input`, and calls `Runner.run_streamed` with the Merak agent.
5. As the agent reasons it may call `search_agents_tool`, which hits OpenAI’s vector store and returns structured results.
6. `stream_agent_response` transforms agent output (assistant messages, tool call status) into `ThreadStreamEvent` instances, which are persisted to `MemoryStore` and streamed to the client.

## Configuration & Environment
- Environment variables are loaded through `app/core/settings.py`:
  - `OPENAI_API_KEY` (required)
  - `VECTOR_STORE_ID` (required)
  - Optional logging flags: `DEBUG`, `LOG_LEVEL`
- `.env` is read automatically; update `.env.example` when introducing new settings.
- No other services are required for local development beyond an active OpenAI account and vector store.

## Data & Persistence
- **Threads / Items:** Stored in memory using `_ThreadState` objects; suited only for demos or single-instance deployments. Replace with a durable store for production.
- **Attachments:** Not supported—`MerakAgentServer.to_message_content` raises `RuntimeError` if an attachment arrives.
- **Vector Data:** Managed externally in the OpenAI vector store backing the `search_agents` tool.

## Operational Notes
- Start the API with `uvicorn app.main:app --reload` after installing dependencies (`pip install -r requirements.txt`).
- Because state is in-memory, restarting the server clears all chat threads. Persisted testing requires replacing `MemoryStore` with a database-backed implementation.
- The ChatKit converter now relies on historial context; if the converter fails, the server logs a fallback and the agent may lose context. Check the SOP for debugging guidance.

## Related Docs
- `.agent/SOP/chatkit_user_message_conversion.md` — explains the conversion fallback and debugging steps.
- `chatkit_server_integration_plan.md` — historical implementation plan for wiring the ChatKit server.
- `.agent/Tasks/task-chatkit-route-hardening.md` — follow-up task to harden the FastAPI response handling.
