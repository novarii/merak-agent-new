"""FastAPI entrypoint wiring the ChatKit server and REST endpoints."""

from __future__ import annotations

from typing import Any

from chatkit.server import StreamingResult
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from starlette.responses import JSONResponse

from .auth.dependencies import SupabaseUser, get_current_user
from .chat import (
    MerakAgentServer,
    create_chatkit_server,
)

app = FastAPI(title="MerakAgent API")

_chatkit_server: MerakAgentServer | None = create_chatkit_server()

def get_chatkit_server() -> MerakAgentServer:
    if _chatkit_server is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "ChatKit dependencies are missing. Install the ChatKit Python "
                "package to enable the conversational endpoint."
            ),
        )
    return _chatkit_server

@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _chatkit_server is not None:
        await _chatkit_server.aclose()

@app.post("/chatkit")
async def chatkit_endpoint(
    request: Request,
    server: MerakAgentServer = Depends(get_chatkit_server),
    user: SupabaseUser = Depends(get_current_user),
) -> Response:
    payload = await request.body()
    context = {"request": request, "user_id": user.id, "user": user}
    result = await server.process(payload, context)
    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
