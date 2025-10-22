# ChatKit User Message Conversion SOP

# ChatKit User Message Conversion SOP

## Purpose
Ensure incoming ChatKit thread items are translated into the OpenAI Agents SDK format while preserving chat history. The Merak backend now leans on `ThreadItemConverter.to_agent_input` so the agent receives the full dialogue context before calling tools.

## Canonical Flow
1. **Instantiate the converter:** `MerakAgentServer.__init__` sets `self._thread_item_converter = self._init_thread_item_converter()`.
2. **Load recent history:** `_to_agent_input` fetches the latest 50 items from `MemoryStore`, reverses them to chronological order, and appends the current item if it has not been persisted yet.
3. **Filter relevant entries:** Keep only `UserMessageItem`, `AssistantMessageItem`, and `ClientToolCallItem` instances, trimming to the most recent ~12 elements to stay within token budgets.
4. **Convert in bulk:**
   ```python
   if converter and relevant:
       to_agent = getattr(converter, "to_agent_input", None)
       if callable(to_agent):
           return await to_agent(relevant)
   ```
   `to_agent_input` returns a list of response input items that the Agents SDK can consume directly.

## Fallback Path — Plain Text Extraction
- When conversion raises `TypeError` or the converter is unavailable, walk the filtered history from newest to oldest and return the most recent `UserMessageItem` text via `_user_message_text`.
- This keeps the server responsive but drops assistant/tool context; investigate logs and enhance the converter before relying on the fallback in production.

## Troubleshooting
- **Converter missing?** Verify `openai-chatkit` is installed and matches the version declared in `requirements.txt` (`1.0.2`).
- **Unexpected item types?** Custom widgets or hidden context require overriding the relevant `ThreadItemConverter` methods (`widget_to_input`, `hidden_context_to_input`).
- **Repeated fallbacks?** Enable extra logging around `_to_agent_input` to capture the raw items being filtered; confirm that the converter supports them or adjust the filter list.

## Related Docs
- `.agent/System/project_architecture.md` — architectural overview and request flow.
- `chatkit_server_integration_plan.md` — historical integration notes and outstanding tasks.
