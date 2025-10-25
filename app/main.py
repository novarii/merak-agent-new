"""FastAPI entrypoint wiring the ChatKit server and REST endpoints."""

from __future__ import annotations

from typing import Any

from chatkit.server import StreamingResult
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from starlette.responses import JSONResponse

from .auth.dependencies import SupabaseUser, get_current_user
from .chat import (
    MerakAgentServer,
    create_chatkit_server,
)
from .core.settings import settings

app = FastAPI(title="MerakAgent API")

def _parse_cors_origins(raw: str | None) -> list[str]:
    if raw is None:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

cors_origins = _parse_cors_origins(settings.cors_origins)
allow_credentials = bool(cors_origins) and "*" not in cors_origins
if not cors_origins:
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


app.add_api_route(
    "/chatkit/",
    chatkit_endpoint,
    methods=["POST"],
    include_in_schema=False,
)

@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}
