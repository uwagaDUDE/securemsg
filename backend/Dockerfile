# ── SecureMsg backend (FastAPI + Socket.IO) ──
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Pinned full dependency set (root requirements.txt includes cryptography,
# python-dotenv, etc. that backend/requirements.txt omits).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code. frontend/ is also copied because main.py mounts it as a
# StaticFiles fallback; nginx serves it in production, so this is just a safety net.
COPY backend ./backend
COPY frontend ./frontend
COPY run.py ./

EXPOSE 8111

# Behind nginx → plain HTTP, no --reload (that's dev-only in run.py).
# TLS is terminated by nginx.
# --proxy-headers + --forwarded-allow-ips=* makes uvicorn populate
# request.client.host from X-Forwarded-For, so the per-IP rate limiter sees the
# real client instead of nginx's container IP. Safe here: the backend is only
# reachable on the internal Docker network (no published ports), so the only
# source of these headers is our own nginx.
CMD ["uvicorn", "backend.app.main:socket_app", \
     "--host", "0.0.0.0", "--port", "8111", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
