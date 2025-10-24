# SOP: Consuming ChatKit SSE Streams in the Frontend

## Purpose
Explain how frontend clients should send ChatKit requests and process streaming responses so progress events (e.g., `search_animation:start|stop`) reliably toggle UI state.

## Prerequisites
- Backend deployed with `/chatkit` endpoint (FastAPI + ChatKit server).
- Redis configured via `REDIS_URL` so threads persist (optional but recommended).
- Frontend environment capable of streaming `fetch` responses (modern browsers or Node `fetch` polyfills).

## Workflow

1. **Build the request payload**
   - Use one of the streaming ChatKit operations. For Merak Agent the flow is:
     - `threads.create` for the very first turn (optional—same streaming pattern).
     - `threads.add_user_message` for every follow-up user message.
   - Payload shape:
     ```json
     {
       "type": "threads.add_user_message",
       "params": {
         "thread_id": "<thread-id>",
         "input": {
           "type": "user_message",
           "content": [
             { "type": "input_text", "text": "Find frontend engineers" }
           ],
           "attachments": [],
           "inference_options": {}
         }
       }
     }
     ```
   - Include the current `thread_id`; the backend rejects unknown threads.

2. **POST and keep the connection open**
   - Call `fetch("/chatkit", { method: "POST", body: JSON.stringify(payload) })`.
   - Do **not** await `response.json()`. Instead, read `response.body` as a stream:
     ```ts
     const response = await fetch("/chatkit", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify(payload),
       signal: abortController.signal,
     });
     const reader = response.body?.getReader();
     ```
   - Abort with `AbortController` if the user navigates away.

3. **Parse `text/event-stream` chunks**
   - ChatKit sends SSE-formatted lines (`data: {...}\n\n`). Accumulate text with a `TextDecoder`, split on double newlines, and `JSON.parse` each `data:` block.
   - Each parsed object is a `ThreadStreamEvent`:
     - `assistant_message`, `client_tool_call`, `thread_item_done`, `progress_update`, etc.

4. **Toggle the search animation**
   - Listen for `event.type === "progress_update"`.
   - `event.text === "search_animation:start"` → start spinner.
   - `event.text === "search_animation:stop"` → stop spinner.
   - Handle other events (assistant text, tool calls) with existing UI logic.

5. **Finish the turn**
   - When `reader.read()` returns `{ done: true }`, the server closed the stream (turn complete).
   - Flush any buffered partial chunk, then allow the UI input to accept the next user message.

## Reference Implementation

```ts
type ThreadStreamEvent =
  | { type: "assistant_message"; /* ... */ }
  | { type: "client_tool_call"; /* ... */ }
  | { type: "thread_item_done"; /* ... */ }
  | { type: "progress_update"; text: string }
  | { type: "error"; message: string };

function parseSse(buffer: string): ThreadStreamEvent[] {
  const events: ThreadStreamEvent[] = [];
  for (const block of buffer.split("\n\n")) {
    if (!block.trim()) continue;
    const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
    if (!dataLine) continue;
    try {
      events.push(JSON.parse(dataLine.replace(/^data:\\s*/, "")));
    } catch (err) {
      console.warn("Invalid SSE chunk", err);
    }
  }
  return events;
}

export async function sendStreamedUserMessage(
  threadId: string,
  text: string,
  onEvent: (event: ThreadStreamEvent) => void,
  signal?: AbortSignal,
) {
  const payload = {
    type: "threads.add_user_message",
    params: {
      thread_id: threadId,
      input: {
        type: "user_message",
        content: [{ type: "input_text", text }],
        attachments: [],
        inference_options: {},
      },
    },
  };

  const response = await fetch("/chatkit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });

  const reader = response.body?.getReader();
  if (!reader) throw new Error("Streaming response missing body");

  const decoder = new TextDecoder();
  let carry = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    carry += decoder.decode(value, { stream: true });
    const events = parseSse(carry);

    const lastSplit = carry.lastIndexOf("\n\n");
    if (lastSplit !== -1) {
      carry = carry.slice(lastSplit + 2);
    }

    for (const event of events) onEvent(event);
  }
}
```

### Handling the animation
```ts
sendStreamedUserMessage(threadId, userInput, (event) => {
  if (event.type === "progress_update") {
    if (event.text === "search_animation:start") showSpinner();
    if (event.text === "search_animation:stop") hideSpinner();
    return;
  }
  // existing handlers for assistant messages, tool calls, etc.
});
```

## Troubleshooting
- **No `progress_update` events**: the agent hasn’t reached the search tool yet. Wait for a turn where the tool executes.
- **`TypeError: Failed to fetch`**: browser blocked CORS. Ensure `/chatkit` allows the frontend origin.
- **Stream ends immediately**: payload missing required fields (`thread_id`, `inference_options`). Match the schema (`threads.add_user_message` JSON schema).
- **Redis keys missing**: verify `REDIS_URL` is set in the API environment; without it, threads fall back to in-memory storage and vanish on restart (streaming still works).
