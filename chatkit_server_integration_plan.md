# ChatKit Server Integration Plan

## Background
- **Goal:** expose the existing `merak_agent` (`app/merak_agent.py`) through a ChatKit-compatible backend so the Next.js + React frontend can drive real conversations with the Merak toolchain.
- **Current Agent:** `merak_agent` uses OpenAI `gpt-4.1-mini` and the `search_agents` tool. It already encapsulates the orchestration logic for gathering hiring requirements and performing a vector-store lookup.
- **Existing Infrastructure:** we have an in-memory ChatKit `Store` implementation (`app/memory_store.py`). There is a partially stubbed `MerakAgentServer` in `app/main.py`, but it currently misses imports, context plumbing, and conversion helpers.

## High-Level Architecture
1. **Context Layer:** Provide a `MerakAgentContext` that extends `chatkit.agents.AgentContext`, injecting the in-memory store and any request-scoped metadata (authentication, analytics hooks, etc.).
2. **ChatKit Server:** Subclass `ChatKitServer` to stream agent responses, persist thread items via `MemoryStore`.
3. **FastAPI Integration:** Expose the ChatKit server via ASGI route (`POST /chatkit`) so the frontend can communicate using ChatKit’s protocol.
4. **Configuration:** Reuse `app/core/settings.py` for API keys and vector store IDs. Ensure `.env.example` is updated if new secrets are required (none expected beyond existing OpenAI credentials).

## Detailed Implementation Steps

### 1. Finalize the Agent Context
- **File:** start in `app/main.py`; if the context grows, move it to a dedicated module such as `app/chat_server/context.py`.
- **Action:** Define a typed dataclass/Pydantic model to hold per-request data (store, auth/session info) so downstream helpers receive a consistent shape.
- **Agent attachment:** Inside `MerakAgentServer.__init__`, instantiate the wrapped Merak agent once and store it on `self.assistant`, e.g. `self.assistant = Agent[MerakAgentContext](model=MODEL, instructions=MERAK_AGENT_INSTRUCTIONS, tools=[search_agents_tool])`. `respond` will call `Runner.run_streamed(self.assistant, ...)` so the server reuses the same agent each request.
- **Why it matters:** `AgentContext` is the runtime envelope the Agents SDK uses to stream everything back to the ChatKit client. It holds the active thread metadata plus request-scoped state, and exposes helpers like `stream(...)`, `stream_widget(...)`, and the `client_tool_call` slot so tool functions can send intermediate events without manually constructing ChatKit payloads. By subclassing it (`MerakAgentContext`), we can tuck in our `MemoryStore`, auth/session details, and any future telemetry hooks while keeping the runner/streaming APIs intact.

```python
from chatkit.agents import AgentContext
from app.memory_store import MemoryStore

class MerakAgentContext(AgentContext):
    store: MemoryStore
    request_context: dict[str, Any]
```

### 2. Implement Thread Item Conversion
- **Source of truth:** `chatkit.agents.ThreadItemConverter` already knows how to translate thread items into Agents SDK inputs when given recent history.
- **Plan:** initialize the converter in the server constructor and, inside `_to_agent_input`, load the last ~50 thread items, filter to user/assistant/tool messages, and hand that list to `converter.to_agent_input(relevant_items)`. If conversion fails, fall back to `_user_message_text` for the newest user message.

### 3. Stream Agent Responses Via Runner
- **Reference:** `Runner.run_streamed(self.assistant, agent_input, context=agent_context)` from the sample fact server. `self.assistant` should point to `merak_agent`.
- **Implementation sketch:**

```python
async def respond(
    self,
    thread: ThreadMetadata,
    item: UserMessageItem | None,
    context: dict[str, Any],
) -> AsyncIterator[ThreadStreamEvent]:
    agent_context = MerakAgentContext(thread=thread, store=self.store, request_context=context)

    target_item = item or await self._latest_thread_item(thread, context)
    if target_item is None:
        return

    agent_input = await self._to_agent_input(thread, target_item)
    if agent_input is None:
        return

    result = Runner.run_streamed(self.assistant, agent_input, context=agent_context)
    async for event in stream_agent_response(agent_context, result):
        yield event
```

### 4. Persist Thread Items
- Reuse `_latest_thread_item` and `_to_agent_input` helpers from the reference snippet. Adjust docstrings and ensure they rely on `MemoryStore` methods (`load_thread_items`, `add_thread_item`, etc.).
- Hidden context items (`HiddenContextItem`) are optional. The Merak agent does not currently need them because the frontend shows regular assistant/tool messages only; skip `_add_hidden_item` unless we later introduce silent confirmations or metadata broadcasts.

### 5. Handle Tool Completions
- Filter out `ClientToolCallItem` instances in `_to_agent_input` so we do not echo tool completions back into the agent loop.
- Update the agent context to surface the latest `ClientToolCall` so the frontend can render tool call metadata (themes/weather analogues not needed yet but pattern is ready).

### 6. FastAPI Wiring
- **Missing code today:** There is no FastAPI app wiring to expose `ChatKitServer.process`. We need a router similar to:

```python
from fastapi import APIRouter, Request

router = APIRouter()
server = MerakAgentServer(agent=merak_agent)

@router.post("/chatkit")
async def process(req: Request) -> Response:
    body = await req.body()
    result = await server.process(body, context={})
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if isinstance(result, NonStreamingResult):
        return Response(content=result.json, media_type="application/json")
    raise HTTPException(status_code=500, detail=f"Unexpected result type: {type(result).__name__}")
```

- **Resolved detail:** In `openai-chatkit==1.0.2`, `ChatKitServer.process` returns either `StreamingResult` (an `AsyncIterable[bytes]`) or `NonStreamingResult` (wrapping raw `bytes`). Neither exposes `to_response()`, so the FastAPI route should detect the return type and wrap it manually: `StreamingResponse(result, media_type="text/event-stream")` for streaming, `Response(content=result.json, media_type="application/json")` otherwise.

## 7. Documentation Touchpoint
- Add a brief note in `.agent/README.md` once the prototype is ready, so other contributors know where to find the plan.

## Open Questions / Ambiguities (Resolved)
- **Input conversion path:** Implemented by batching recent thread history and calling `ThreadItemConverter.to_agent_input`. Plain-text fallback remains for unexpected item types.
- **Assistant handle naming:** Standardised on `self.assistant` defined in `__init__`.
- **Attachments:** Still out of scope; `to_message_content` raises `RuntimeError` until file support is prioritised.

## Related Docs
- `.agent/System/project_architecture.md` — current architecture and request flow.
- `.agent/SOP/chatkit_user_message_conversion.md` — operational guidance for the converter and fallbacks.
- `.agent/Tasks/task-chatkit-route-hardening.md` — follow-up work to improve the FastAPI endpoint resilience.
