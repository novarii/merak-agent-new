# ChatKit User Message Conversion SOP

## Purpose
When wiring the Merak backend to ChatKit, incoming `UserMessageItem` objects must be translated into an agent input structure the OpenAI Agents SDK understands. This guide documents the two-stage fallback approach used in the ChatKit server to keep compatibility with multiple SDK versions.

## Primary Path — `ThreadItemConverter`
1. Ensure `_init_thread_item_converter()` runs during server initialization. It attempts to instantiate `ThreadItemConverter` with the appropriate keyword arguments (e.g., `to_message_content`).
2. Inside `_to_agent_input`, probe the converter for a usable method in this order:
   - `to_input_item`
   - `convert`
   - `convert_item`
   - `convert_thread_item`
3. For whichever method exists, call it with the current `ThreadItem` and pass the `ThreadMetadata` when the signature expects a second positional argument or keyword.

```python
result = method(*call_args, **call_kwargs)
if inspect.isawaitable(result):
    return await result
return result
```

This yields a structured payload (e.g., `ResponseInputContentParam`) ready for `Runner.run_streamed`.

## Fallback Path — Plain Text Extraction
If the converter is missing or none of the methods resolve:
1. Detect raw user messages:
   ```python
   if isinstance(item, UserMessageItem):
       return _user_message_text(item)
   ```
2. Build the text string by walking the message content parts:
   ```python
   def _user_message_text(item: UserMessageItem) -> str:
       parts: list[str] = []
       for part in item.content:
           text = getattr(part, "text", None)
           if text:
               parts.append(text)
       return " ".join(parts).strip()
   ```

This fallback keeps the agent running by providing a simple string input if structured conversion is unavailable.

## Usage Notes
- The converter-first strategy maintains richer context (attachments, tool references) when supported by the SDK version in use.
- The fallback is safe for prototypes but may drop non-textual payloads; add explicit handling if future widgets require it.
- Keep the helper isolated in `_to_agent_input` so we can swap in updated converter APIs without touching the main response loop.
