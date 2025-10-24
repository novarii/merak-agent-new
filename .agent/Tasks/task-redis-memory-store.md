# Task: Replace MemoryStore with Redis and Stream Animation via SSE

## Background
- The current ChatKit backend uses `app/memory_store.py`, an in-memory implementation of `chatkit.store.Store`. This works only for single-process development; state is lost on restart and cannot be shared across workers.
- We recently shifted the search animation indicator from a client tool to `ProgressUpdateEvent` SSE markers (`search_animation:start|stop`). These events need to remain reliable after we swap to Redis.
- The frontend already listens to SSE from `/chatkit` and will trigger/stop the spinner based on those progress updates.

## Goals
1. Replace `MemoryStore` with a Redis-backed store that satisfies the `Store` interface while preserving thread history, tool calls, widgets, and workflow items.
2. Ensure the animation events and other streamed payloads (progress updates, assistant messages, client tool calls) behave identically with Redis.
3. Make datastore configuration environment-driven (host, port, auth, DB index) and document required env vars.

## Non-Goals
- Implementing Redis clustering or sharding (single-instance deployment is sufficient for now).
- Adding persistence for attachments; still out of scope.
- Changing the frontend animation logic—it continues to rely on SSE progress markers.

## Implementation Plan
1. **Introduce Redis store module**
   - Create `app/redis_store.py` implementing `Store[dict[str, Any]]`.
   - Use `redis.asyncio` client. Provide helpers for storing thread metadata, thread items, and generating IDs (either reuse `default_generate_id` or store counters in Redis).
   - Encode thread items as JSON (e.g., Pydantic `.model_dump()`) and store them in Redis lists / hashes. Consider key layout like:
     - `thread:{thread_id}:metadata`
     - `thread:{thread_id}:items` (list of serialized items)
     - `thread:index` for ID generation (bounded increment).
   - Implement every abstract `Store` method (`load_thread`, `load_thread_items`, `add_thread_item`, `save_item`, `load_threads`, etc.); ChatKit calls each one during request processing.
   - Keep `default_generate_id` prefixes (`thr_`, `msg_`, `tc_`, …) unless Redis needs a different scheme—downstream tooling expects those prefixes to infer item type.
   - Strip embedded items when persisting thread metadata so future ChatKit versions with extra fields still deserialize cleanly (mirror `MemoryStore._coerce_thread_metadata`).
2. **Configuration**
   - Add settings in `app/core/settings.py` for `redis_url` or individual host/port credentials.
   - Update `.env.example` to include `REDIS_URL=redis://localhost:6379/0`.
   - In `app/chat.py`, instantiate `RedisStore` instead of `MemoryStore` based on settings, falling back to in-memory when Redis is absent (useful for tests).
3. **Integrate with ChatKit server**
   - Replace `self.store = MemoryStore()` with `self.store = resolve_store()` in `MerakAgentServer.__init__`.
   - Provide graceful teardown (close Redis connection) if necessary.
4. **Migration / scripts**
   - Provide a lightweight script or SOP entry describing how to run Redis locally (Docker compose or brew install) and how to clear stale keys between runs.
   - Add unit tests covering basic store operations: create/save thread, append item, update item, list items.
5. **Validate SSE animation**
   - Confirm `search_animation:start` and `search_animation:stop` progress events stream correctly with Redis store.
   - Ensure `display_agent_profiles` client tool call still succeeds (the Redis store must maintain pending/completed lifecycle).
   - Attachments remain unsupported; implement `save_attachment/load_attachment/delete_attachment` to raise descriptive `NotImplementedError` so ChatKit surfaces helpful errors if those paths are hit.

## Acceptance Criteria
- `uvicorn app.main:app` works with Redis running locally; chat threads persist across multiple requests and survive server reloads.
- Progress updates for the animation flow over SSE exactly once per search cycle.
- Tests for the Redis store pass (`pytest app/tests/...` once added); existing suite remains green.
- Documentation updated in `.agent/System` and `.env.example`.

## Related Docs
- `.agent/System/project_architecture.md` — update to reflect Redis backing store and progress-event animation.
- `.agent/Tasks/task-chatkit-client-tool-call-race.md` — background on the animation/tool-call refactor.
- `app/memory_store.py` — reference for Store contract; should note the Redis replacement once work begins.
- `.agent/Tasks/task-chatkit-multi-user-redis.md` — follow-on task covering per-user namespacing and Supabase-authenticated access.
