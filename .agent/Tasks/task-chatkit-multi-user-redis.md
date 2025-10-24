# Task: Isolate ChatKit Threads Per User in Redis

## Background
- The current Redis-backed store in `app/redis_store.py` namespaces keys solely by `thread_id` (`thread:{thread_id}:*`) and maintains a single global sorted set `_THREAD_INDEX_KEY`. No user context is passed into the store.
- FastAPI’s `/chatkit` route forwards `{"request": request}` to `MerakAgentServer.process`, so the store never sees the Supabase-authenticated user. Multiple signed-in users would therefore load and overwrite each other’s threads.
- Supabase Auth is already provisioned for the product prototype; we only need to surface the validated `user_id` on every request and use it as the partition key for threads and items.

## Goals
1. Enforce that every ChatKit request carries a verified Supabase user and propagate the `user_id` through the ChatKit context.
2. Namespace Redis keys and indexes by `user_id` while preserving the existing pagination behaviour and metadata semantics.
3. Keep the in-memory `MemoryStore` viable for local development by scoping it per user as well, and extend test coverage to prove user isolation.
4. Document how the frontend selects the correct thread (`setThreadId`) and how backend callers should supply the Supabase token.

## Non-Goals
- Implementing attachment persistence or changing the ChatKit item model.
- Replacing Supabase Auth or introducing RBAC/organization hierarchies beyond the raw `user_id`.
- Shipping production-grade rate limiting or auditing (documented as follow-up work if needed).

## Implementation Plan
1. **Surface Supabase user context**
   - Extend `app/core/settings.py` with Supabase-specific fields (project ref/domain, JWT audience, JWKS URL, optional service-role key for server-to-server lookups) and update `.env.example`.
   - Add `app/auth/supabase.py` that caches Supabase JWKS, verifies JWT signatures, checks `aud`/`iss`, and returns a dataclass with at least `user_id`, `email`, and `role`.
   - Create a FastAPI dependency `get_current_user` that pulls the `Authorization: Bearer` header, validates via the helper above, and raises `HTTPException(status_code=401)` on failure. Wire it into `/chatkit` so the handler signature becomes `async def chatkit_endpoint(..., user: SupabaseUser = Depends(get_current_user))`.
   - Ensure shutdown closes any background JWKS refresh tasks if created.

2. **Pass user context into ChatKit**
   - Update `chatkit_endpoint` to call `server.process(payload, {"request": request, "user_id": user.id})`.
   - Audit other server entry points (tool webhooks, batch routes) to ensure they also forward the same context or intentionally restrict access.
   - Add logging at `MerakAgentServer.respond` to include `user_id` for easier tracing (guarded by DEBUG level).

3. **Refactor `RedisStore` for per-user namespacing**
   - Introduce helper functions that derive keys from both `user_id` and `thread_id` (e.g., `chat:user:{user_id}:thread:{thread_id}:meta/items`). Replace `_THREAD_INDEX_KEY` with a per-user sorted set (`chat:user:{user_id}:threads:index`).
   - Add `_require_user_id(context)` that raises `ValueError` (caught and translated to `HTTPException` upstream) when missing, ensuring tests use explicit context.
   - Update all CRUD methods (`save_thread`, `load_thread`, `load_threads`, `add_thread_item`, etc.) to use the new helpers; make sure cross-user calls return `NotFoundError` instead of leaking data.
   - Keep payload encoding exactly as today to avoid downstream format changes. If desired, add optional TTL support via constructor parameter read from settings.
   - Expand `tests/test_redis_store.py` with scenarios covering two distinct users sharing a `thread_id`—each should see only their own items and metadata. Update fixtures to pass `{"user_id": "user_a"}` etc.

4. **Align the memory fallback and server lifecycle**
   - Modify `app/memory_store.py` to store threads keyed by `user_id` (e.g., nested dict) so local runs mirror production behaviour and tests can share the same context contract.
   - Ensure `_create_store` still instantiates `MemoryStore` when Redis is unavailable; no user-specific configuration should be required beyond passing context.
   - Teach `MerakAgentServer.aclose` to close the Redis client only once per process and adjust tests accordingly.

5. **Frontend and documentation updates**
   - Document in `.agent/System/project_architecture.md` how `/chatkit` expects an authenticated Supabase user and how thread IDs are persisted per user in Redis.
   - Update `.agent/Docs/chatkit_server.py` (or create a new SOP entry) with instructions for triggering `chatkit.setThreadId` after login, storing the thread ID in the user profile, and rehydrating it on page load.
   - Add a short paragraph in `.agent/Tasks/task-redis-memory-store.md` cross-referencing this work so maintainers know the multi-user change builds on the earlier Redis plan.

## Acceptance Criteria
- `/chatkit` returns 401 when the Supabase token is missing/invalid and includes `user_id` in the ChatKit context on success.
- Redis keys are stored under `chat:user:{user_id}:thread:{thread_id}:*`, and sorted-set pagination remains correct per user.
- Unit tests cover RedisStore isolation and MemoryStore multi-user behaviour.
- Documentation reflects the new authentication dependency and frontend thread handling requirement.

## Related Docs
- `app/redis_store.py` — current single-tenant Redis implementation.
- `app/memory_store.py` — in-memory fallback that needs per-user scoping.
- `.agent/System/project_architecture.md` — update system overview.
- `.agent/Docs/chatkit_server.py` — reference guide for ChatKit backend wiring.
