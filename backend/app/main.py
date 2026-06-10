import asyncio
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import ALLOWED_ORIGINS
from .database import engine, init_db
from .logging_config import configure_logging, get_logger
from .metrics import (
    http_requests_total,
    http_request_duration_seconds,
    active_websocket_connections,
    metrics_endpoint,
)
from .routers import attachments, auth, blocks, channels, groups, key_verification, messages, permissions, push, users
from .socketio import sio, _user_sessions


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_online = 0"))
    _user_sessions.clear()
    await auth._limiter.load()
    await permissions._limiter.load()
    await channels.ensure_system_channel()
    logger.info("Application startup complete")
    yield
    logger.info("Application shutdown complete")


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    import time
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    http_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
    ).inc()
    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", path=request.url.path, method=request.method)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return await metrics_endpoint()


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(messages.router)
app.include_router(permissions.router)
app.include_router(blocks.router)
app.include_router(channels.router)
app.include_router(groups.router)
app.include_router(key_verification.router)
app.include_router(push.router)
app.include_router(attachments.router)

frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
else:
    logger.warning("Frontend dist directory not found, skipping static mount", path=str(frontend_dir))

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
