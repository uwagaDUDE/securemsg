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
from .routers import attachments, auth, blocks, channels, groups, messages, permissions, push, users
from .socketio import sio, _user_sessions


async def _rate_limit_cleanup():
    while True:
        await asyncio.sleep(300)
        auth._limiter._cleanup()
        permissions._limiter._cleanup()
        await auth._limiter.persist()
        await permissions._limiter.persist()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_online = 0"))
    _user_sessions.clear()
    await auth._limiter.load()
    await permissions._limiter.load()
    await channels.ensure_system_channel()
    cleanup_task = asyncio.create_task(_rate_limit_cleanup())
    yield
    await auth._limiter.persist()
    await permissions._limiter.persist()
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
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

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(messages.router)
app.include_router(permissions.router)
app.include_router(blocks.router)
app.include_router(channels.router)
app.include_router(groups.router)
app.include_router(push.router)
app.include_router(attachments.router)

frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
