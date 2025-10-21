# ChatKit Server Integration Plan

## Background
- **Goal:** expose the existing `merak_agent` (`app/merak_agent.py`) through a ChatKit-compatible backend so the Next.js + React frontend can drive real conversations with the Merak toolchain.
- **Current Agent:** `merak_agent` uses OpenAI `gpt-4.1-mini` and the `search_agents` tool. It already encapsulates the orchestration logic for gathering hiring requirements and performing a vector-store lookup.
- **Existing Infrastructure:** we have an in-memory ChatKit `Store` implementation (`app/memory_store.py`). There is a partially stubbed `MerakAgentServer` in `app/main.py`, but it currently misses imports, context plumbing, and conversion helpers.

## High-Level Architecture
1. **Context Layer:** Provide a `MerakAgentContext` that extends `chatkit.agents.AgentContext`, injecting the in-memory store and any request-scoped metadata (authentication, analytics hooks, etc.).
2. **ChatKit Server:** Subclass `ChatKitServer` to stream agent responses, persist thread items via `MemoryStore`.
3. **FastAPI Integration:** Expose the ChatKit server via ASGI route (`POST /chatkit/process`) so the frontend can communicate using ChatKit’s protocol.
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
- **Source of truth:** `chatkit.agents.ThreadItemConverter` mirrors what we saw in the sample Fact server. Using it prevents duplicating logic for translating ChatKit thread history into agent inputs.
- **Plan:** initialize a converter in the server’s constructor and add a helper that uses any of the exposed `convert_*` methods (similar to the sample). If the converter signature changes across library versions, catch `TypeError` and fall back gracefully.

```python
self._thread_item_converter = ThreadItemConverter(
    to_message_content=self.to_message_content  # raises RuntimeError today because Merak does not support attachments
)
```

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

@router.post("/chatkit/process")
async def process(req: Request) -> StreamingResponse:
    body = await req.body()
    result = await server.process(body, context={})
    return result.to_response()
```

- **Resolved detail:** In `openai-chatkit==1.0.2`, `ChatKitServer.process` returns either `StreamingResult` (an `AsyncIterable[bytes]`) or `NonStreamingResult` (wrapping raw `bytes`). Neither exposes `to_response()`, so the FastAPI route should detect the return type and wrap it manually: `StreamingResponse(result, media_type="text/event-stream")` for streaming, `Response(content=result.json, media_type="application/json")` otherwise.

## 7. Documentation Touchpoint
- Add a brief note in `.agent/README.md` once the prototype is ready, so other contributors know where to find the plan.

## Open Questions / Ambiguities (RESOLVED)
- Input conversion path: `app/main.py` still references `ThreadMetadata`, `UserMessageItem`, and a missing `simple_to_agent_input`. The prototype should first attempt to initialize a `ThreadItemConverter` via `_init_thread_item_converter()` and use a defensive `_to_agent_input` helper that probes common method names (`to_input_item`, `convert`, `convert_item`, `convert_thread_item`). If no converter is available—or it lacks those methods—we fall back to `_user_message_text(item)` to extract plain text from `UserMessageItem` instances. We need to confirm which branch works once we wire everything together.
- Assistant handle naming: the reference docs expose an `assistant_agent` class attribute, but we’re standardizing on an instance attribute `self.assistant` set in `__init__`. Update the stub to drop `self.assistant_agent` references so `respond` always calls `Runner.run_streamed(self.assistant, ...)`.
- File attachments are not in scope yet. The `to_message_content` method may simply raise `RuntimeError` like the sample.
