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
   - Note in the task description and linked docs that the Chat experience spans the FastAPI backend (Merak agent search + streaming) and the full-stack Next.js server, which proxies ChatKit traffic and executes client-tool callbacks.
   - Confirm the Next runtime (Edge vs. Node) so server-side Supabase queries can run where client-tool calls are handled.
1. **Emit client tool call (FastAPI)**
   - In `app/merak_agent_tool.py`, after `vector_stores.search`, gather IDs with the existing `extract_agent_ids`.
   - Introduce a helper (e.g., `dispatch_agent_profiles`) that sets `ctx.context.client_tool_call = ClientToolCall(name="display_agent_profiles", arguments={"agent_ids": agent_ids})`.
   - Register this helper in the Merak agent definition and set `tool_use_behavior=StopAtTools(stop_at_tool_names=["display_agent_profiles"])` so ChatKit pauses until the client acknowledges the tool.
   - Maintain the textual summary output for the LLM response, but rely on the client tool to deliver IDs to the front end.
   - Add backend coverage ensuring a tool invocation populates `client_tool_call`.
2. **Document client-tool contract**
   - Update `.agent/System/project_architecture.md` (or equivalent) to capture the new call flow: FastAPI triggers `display_agent_profiles` → Next.js handler fetches Supabase → UI updates.
   - Cross-link any Next.js documentation so the FE team knows the tool name, payload shape, and stop-at behavior.
3. **Next.js client tool handler**
   - In `src/components/ChatKitPanel.tsx`, keep the two-column layout but wire `useChatKit` with `onClientTool` (or `clientTools` once available) so `display_agent_profiles` invokes the `useAgentProfiles().loadProfiles` hook.
   - Ensure the handler returns the hook’s `{ success, count, error }` object so ChatKit resumes streaming only after the Supabase fetch/state update resolves.
   - Reset agent profiles when threads change (`onThreadChange` already clears state in your hook).
4. **Supabase lookup API (Next.js server)**
   - Implement or refine `app/api/agents/route.ts` to accept `{ agentIds }`, validate input, and query Supabase with `.in("agent_id", agentIds)`.
   - Load `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from environment; update `.env.local` / `.env.example`.
   - Shape the response so `useAgentProfiles` can map directly to UI props; add lightweight tests if feasible.
5. **Profile column rendering**
   - Replace the placeholder panel on the right column (`app/page.tsx`) with a component that consumes `useAgentProfiles` state (loading, error, profiles) and renders cards with key fields (name, role, rate, availability, industry tags).
   - Show skeleton/loading states while `loadProfiles` runs; clear profiles between searches to avoid stale data.
6. **Error handling & telemetry**
   - Handle Supabase/API failures gracefully (show a brief inline message while keeping the chat stream alive).
   - Optionally log Supabase errors to the browser console in dev and to an observability hook in prod.
7. **Validation & rollout**
   - End-to-end test: start a local chat, confirm the Merak narration streams while rich profiles render shortly after the tool call.
   - Update `.agent/README.md` index and any SOP that references search tooling.
   - Prepare a short Loom or screenshot walkthrough if that’s part of team rollout norms.

## Acceptance Criteria
- FastAPI sets `ctx.context.client_tool_call` with `name="display_agent_profiles"` and the expected `agent_ids` payload whenever the search tool runs.
- Next.js ChatKit client handles that client tool, triggers Supabase fetching via `useAgentProfiles`, and resumes streaming once the handler resolves.
- Supabase service keys remain server-side; no secrets leak to the browser or repo.
- UI displays the corresponding profiles within the same chat session and handles empty/error states gracefully.
- All existing tests pass; new coverage added where logic changed (client tool emission, API route, FE hook/component).

## Related Docs
- `.agent/System/project_architecture.md` — Source of truth for backend/FE data flow (update with new stream field).
- `.agent/SOP/chatkit-tooling.md` (create/update if we maintain SOP for tool integrations).
- `feat-nextjs-chatkit-frontend.md` — Align implementation tasks with the broader Next.js frontend feature plan.
