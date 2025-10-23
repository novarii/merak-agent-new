# Task: Resolve ChatKit Client Tool Call Race

## Background
- The Merak search flow emits `run_search_animation` as a client tool so the frontend can toggle a loading indicator while the backend queries OpenAI's vector store.
- After refactoring `app/merak_agent_tool.py` to stream those tool calls (instead of relying solely on `ctx.context.client_tool_call`), the backend began throwing `ValueError: Last thread item in <thread_id> was not a ClientToolCallItem`.
- The error originates in `chatkit.server.ChatKitServer._process_streaming_impl` when processing a `threads.add_client_tool_output` request: ChatKit fetches the most recent thread item and expects a **pending** `ClientToolCallItem`. The new helper we added immediately streams a `ThreadItemDoneEvent` with `status="completed"`, so the store never contains a pending entry.
- Even after adjusting the helper to wait on store updates and marking items completed, the race persists because our FastAPI server never queues the intermediate **pending** `ClientToolCallItem` that ChatKit expects to reconcile with the client.

## Current Behaviour
- Server logs show successful search runs until the frontend acknowledges the `display_agent_profiles` tool. Immediately afterwards, `_cleanup_pending_client_tool_call` logs warnings such as `Client tool call tc_ef87dc4c was not completed, ignoring` and the request fails with:
  ```
  ValueError: Last thread item in thr_5243870e was not a ClientToolCallItem
  ```
- The frontend still receives `run_search_animation` events, but the backend terminates the SSE stream and drops the request. Retrying the same interaction reproduces the crash consistently.
- Running the API under `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1` does not affect the issue (single-worker execution is already required because `MemoryStore` is process-local).

## Reproduction Steps
1. Start the backend with the above `uvicorn` command and connect the ChatKit frontend.
2. Submit any query that triggers `search_agents`.
3. Observe the FastAPI logs: after `[SEARCH] animation OFF…`, the server emits the ValueError and returns a 500 response. The error occurs regardless of whether the frontend acknowledges the tool call.

## Investigation Notes
- ChatKit's spec (see https://openai.github.io/chatkit-python/server#trigger-client-side-tools-from-agent-sdk-in-python) documents two supported patterns:
  1. Set `ctx.context.client_tool_call = ClientToolCall(...)` and let ChatKit emit the pending item automatically at the end of the run.
  2. Manually stream a `ClientToolCallItem` **with `status="pending"`**, then rely on the client to post `threads.add_client_tool_output`, which ChatKit upgrades to `status="completed"`.
- Our helper streams the item directly with `status="completed"` and never exposes a pending entry. As soon as the client POSTs the acknowledgement, ChatKit looks for a pending record and fails, causing the ValueError.
- Attempting to poll `ctx.context.store.load_thread_items` to detect completion does not help because the store is only updated after ChatKit processes the client response. By that time, the pending entry has already been discarded.
- Rolling back to the pre-streamed approach reintroduces the original symptom (no animation tool call reaches the client), so we need a compliant solution rather than remove the feature.

## Open Questions
- Can we hook into ChatKit's `client_tool_call` queue without bypassing its pending/completed lifecycle (e.g., by setting `ctx.context.client_tool_call` twice in a single run)?
- Is there a recommended strategy to emit **multiple** client tools within one tool run (animation start/stop + profile display) while preserving ChatKit's state machine?
- Would adding an explicit `StopAtTools` behaviour or splitting the animation toggles into separate logical runs simplify the contract?

## Proposed Next Steps
1. **Rework tool-call emission** so the start and stop events participate in ChatKit's lifecycle:
   - First emit a pending `ClientToolCallItem` (via `ctx.context.stream(...)` with default status) for `run_search_animation` start.
   - Allow the frontend to acknowledge it with `threads.add_client_tool_output`.
   - Emit the stop call only after the acknowledgement or switch to a single animation tool that the frontend interprets as start/stop based on payload.
2. **Sync with OpenAI ChatKit maintainers** (Context7 doc references) to confirm best practice for multiple client tools per invocation and whether the stop event should occur inside a new run.
3. **Add backend diagnostics** (structured logging around tool call IDs and statuses) so we can verify the lifecycle in future debugging sessions.
4. **Update frontend tooling** to ensure it always POSTs acknowledgements; confirm no retries or race conditions exist on the FE side.

## Related Docs
- `.agent/System/project_architecture.md` — needs an update once the new tool-call strategy is settled.
- `.agent/SOP/chatkit_user_message_conversion.md` — add notes on the pending/completed contract for client tools.
- `app/merak_agent_tool.py` — current helper implementation that requires redesign.
