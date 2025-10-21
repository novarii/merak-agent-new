# Task: Harden ChatKit Endpoint Response Handling

## Background
`app/main.py` currently proxies ChatKit requests through a single `/chatkit` FastAPI route. The implementation only type-checks for `StreamingResult` and otherwise assumes the returned object has a `.json` attribute. This is brittle—`NonStreamingResult` is the intended non-streaming outcome, and unknown types should produce a fast, logged failure rather than a silent downgrade to `JSONResponse`.

## Goal
Update the endpoint to handle ChatKit server responses deterministically: support streaming vs. non-streaming explicitly and surface unexpected result types as 500 errors for easier debugging.

## Implementation Notes
```python
@app.post("/chatkit")
async def chatkit_endpoint(
    request: Request,
    server: MerakAgentServer = Depends(get_chatkit_server),
) -> Response:
    payload = await request.body()
    result = await server.process(payload, {"request": request})

    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")

    if isinstance(result, NonStreamingResult):
        return Response(content=result.json, media_type="application/json")

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected result type: {type(result).__name__}",
    )
```

## Acceptance Criteria
- The route distinguishes `StreamingResult` vs. `NonStreamingResult` using `isinstance` checks.
- Any other return shape triggers an HTTP 500 with a descriptive error message.
- Optional: add logging for the fallback branch if deeper diagnostics are needed.
