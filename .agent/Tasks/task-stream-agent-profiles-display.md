# Task: Stream Agent Profiles into Next.js UI

## Background
- The `search_agents` tool returns lightweight agent summaries from the OpenAI vector store. Each record includes an `attributes.agent_id` field that can be mapped to richer profiles stored in Supabase.
- The FE (Next.js) currently streams Merak's narration from the `/chatkit` endpoint but does not surface the detailed Supabase profile data during the conversation.
- We already have an `extract_agent_ids` helper in `app/merak_agent_tool.py` that can gather the IDs from the tool response, but we do not forward them through the stream or hydrate them in the UI.

## Goals
- Ensure agent IDs recovered from the semantic search are surfaced to the Next.js client in real time.
- Fetch detailed agent profiles from Supabase the moment a tool response completes and render them alongside Merak's explanation.
- Keep the streaming UX smooth: no blocking Merak's narration while profile data loads.
- Maintain separation of concerns: secure Supabase calls happen server-side (Next API route or FastAPI) so browser never sees service keys.

## Non-Goals
- Replacing the existing Supabase schema or seeding new profile data.
- Changing the ChatKit interaction model beyond conveying agent IDs and optional profile previews.
- Implementing bookmarking/shortlisting workflows; focus is on read-only display during a chat session.

## Implementation Plan
0. **Clarify integration boundary**
   - Note in the task description and linked docs that the Chat experience spans the FastAPI backend (merak-agent search + streaming) and the full-stack Next.js server, which proxies ChatKit traffic and will fan out Supabase profile fetches.
   - Confirm the Next runtime (Edge vs. Node) so server-side Supabase queries can run where the FastAPI IDs land.
1. **Augment tool payload (FastAPI)**
   - In `app/merak_agent_tool.py`, call `extract_agent_ids(results)` right after the vector search.
   - Add the list to the JSON payload, e.g. `tool_payload["agent_ids"] = agent_ids`.
2. **Define streaming contract**
   - Document in `.agent/System` how tool responses now include an `agent_ids` array.
   - (Optional) add a short integration note in the Next repo’s docs so FE developers know to expect the field.
3. **Next.js SSE buffering**
   - Update the ChatKit stream handler so tool output is buffered until the `output_text.completed` event arrives; only then `JSON.parse` the text.
   - Store the parsed payload in component state, exposing both the summary and `agent_ids`.
   - Guard against duplicate IDs via `new Set(agentIds)` before triggering downstream fetches.
4. **Supabase lookup API**
   - Implement `app/api/agents/route.ts` (or extend existing route) that accepts `{ agentIds: string[] }`.
   - Use the Supabase server client with `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` loaded from env (update `.env.local` / `.env.example`).
   - Query `agent_profiles` with `.in("agent_id", agentIds)` and return normalized JSON `{ profiles }`.
   - Add unit/integration tests if the FE repo uses Jest/Playwright; otherwise smoke-test manually.
5. **Client-side rendering**
   - When the agent IDs state changes, fire a `fetch("/api/agents", { method: "POST", body: JSON.stringify({ agentIds }) })`.
   - Show a “Loading profiles…” placeholder while awaiting the response, then render cards with headline fields (photo, role, rate, success rate, availability, industry tags).
   - Ensure the UI updates incrementally: if a new search happens, clear stale profiles before showing the next set.
6. **Error handling & telemetry**
   - Handle Supabase/API failures gracefully (show a brief inline message while keeping the chat stream alive).
   - Optionally log Supabase errors to the browser console in dev and to an observability hook in prod.
7. **Validation & rollout**
   - End-to-end test: start a local chat, confirm the Merak narration streams while rich profiles render shortly after the tool call.
   - Update `.agent/README.md` index and any SOP that references search tooling.
   - Prepare a short Loom or screenshot walkthrough if that’s part of team rollout norms.

## Acceptance Criteria
- Tool payload includes an `agent_ids` array populated from search results.
- Next.js client consumes the stream, extracts IDs after tool completion, and hydrates Supabase profiles without blocking other stream events.
- Supabase service keys remain server-side; no secrets leak to the browser or repo.
- UI displays the corresponding profiles within the same chat session and handles empty/error states gracefully.
- All existing tests pass; new coverage added where logic changed (tool payload, API route, FE handler).

## Related Docs
- `.agent/System/project_architecture.md` — Source of truth for backend/FE data flow (update with new stream field).
- `.agent/SOP/chatkit-tooling.md` (create/update if we maintain SOP for tool integrations).
- `feat-nextjs-chatkit-frontend.md` — Align implementation tasks with the broader Next.js frontend feature plan.
