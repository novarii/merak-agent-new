# Task: Bind ChatKit Threads to Supabase Users (Frontend)

## Background
- The backend now requires a Supabase-authenticated user for every `/chatkit` request and scopes Redis keys under `chatkit:user:{user_id}:thread:{thread_id}`.
- Existing Next.js demos rely on ChatKit’s internal default thread, so without explicit thread selection each signed-in user would still collide on the same thread namespace.
- The `useChatKit` hook already offers imperative helpers (`setThreadId`, `createThread`, `onThreadChange` callbacks) but the project doesn’t persist or restore thread IDs per user yet.

## Goals
1. Ensure every ChatKit request from the frontend carries the current user’s Supabase access token in the `Authorization` header.
2. Persist a unique `threadId` per Supabase user and call `setThreadId` before sending or receiving messages so the backend resolves the correct Redis namespace.
3. Store and rehydrate the user’s `threadId` on login or page refresh, and sync updates when ChatKit emits `onThreadChange`.
4. Provide user-facing error handling for 401 responses (token expiry) and missing thread IDs.

## Implementation Plan
1. **Auth wiring**
   - Retrieve the Supabase session token via the JS client (`supabase.auth.getSession()` or the auth helpers already in use).
   - When initializing the ChatKit client/SDK, inject a fetch interceptor or request factory that attaches `Authorization: Bearer <access_token>`.
   - Handle token refresh by listening to Supabase’s auth state changes and updating the ChatKit client when a new access token is issued.

2. **Thread persistence**
   - On successful login, request the user’s saved `threadId` (e.g., via `/api/me/thread` or local storage fallback). If none exists, create a new ChatKit thread (REST call or `chatkit.createThread()`) and persist the mapping.
   - Call `chatkit.setThreadId(threadId)` before rendering the chat UI or sending the first message so subsequent events hit the user-scoped Redis keys.
   - Persist the resolved `threadId` alongside the Supabase user in your frontend store (React state, zustand, or React Query cache) for quick access.

3. **Sync with ChatKit events**
   - Subscribe to `onThreadChange` from the ChatKit component/hook. When it emits a new `threadId` (e.g., user switched threads manually), update the stored mapping and ensure the backend is notified if required.
   - For SSR or deep links, read the thread ID from query params or the stored mapping before hydrating the ChatKit component.

4. **Error & UX handling**
   - Detect `401 Unauthorized` responses from `/chatkit` and prompt the user to reauthenticate (trigger Supabase login, refresh the token, and retry).
   - Show a friendly message when no thread can be resolved (e.g., network failure), and block message submission until `setThreadId` succeeds.

5. **Documentation & QA**
   - Document the thread-selection flow in the frontend README or `.agent/SOP` with notes on where the mapping is stored and how to rotate tokens locally.
   - Smoke-test with two Supabase users in different browsers to verify isolated histories and persistence across page reloads.

## Acceptance Criteria
- The frontend always sends a valid Supabase Bearer token with `/chatkit` calls.
- Each user resumes their own ChatKit thread after login or refresh, with `setThreadId` invoked before sending messages.
- Switching users results in distinct conversation histories; no cross-user contamination occurs.
- Token expiry produces a clear reauth path, and documentation explains the required setup.

## Related Docs
- `.agent/System/project_architecture.md` — backend multi-tenant context and Redis namespacing.
- `.agent/Docs/chatkit_user_message_conversion.md` — ChatKit usage references.
- Backend task: `.agent/Tasks/task-chatkit-multi-user-redis.md` for the corresponding server-side changes.
