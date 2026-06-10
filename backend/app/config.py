import base64
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import load_dotenv

_BASE = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BASE / ".env"

# ── ensure .env with all secrets ──

_existing = {}
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, encoding="utf-8")
    _existing = {k: v for k, v in os.environ.items()}  # snapshot

_lines = []
_jwt = os.getenv("JWT_SECRET")
if not _jwt:
    _jwt = secrets.token_urlsafe(32)
    _lines.append(f"JWT_SECRET={_jwt}")
    os.environ["JWT_SECRET"] = _jwt

_vapid_priv = os.getenv("VAPID_PRIVATE_KEY")
_vapid_pub = os.getenv("VAPID_PUBLIC_KEY")
if not _vapid_priv or not _vapid_pub:
    key = ec.generate_private_key(ec.SECP256R1())
    priv_raw = key.private_numbers().private_value.to_bytes(32, "big")
    pub_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    _vapid_priv = base64.urlsafe_b64encode(priv_raw).rstrip(b"=").decode()
    _vapid_pub = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()
    _lines.append(f"VAPID_PRIVATE_KEY={_vapid_priv}")
    _lines.append(f"VAPID_PUBLIC_KEY={_vapid_pub}")
    os.environ["VAPID_PRIVATE_KEY"] = _vapid_priv
    os.environ["VAPID_PUBLIC_KEY"] = _vapid_pub

if _lines:
    mode = "w" if not _ENV_FILE.exists() else "a"
    header = "# Auto-generated -- do not commit\n" if mode == "w" else ""
    with open(_ENV_FILE, mode, encoding="utf-8") as f:
        f.write(header + "\n".join(_lines) + "\n")

# ── config ──

_DB_PATH = _BASE / "messenger.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}")
JWT_SECRET = _jwt
_JWT_PREVIOUS = os.getenv("JWT_SECRET_PREVIOUS", "")
JWT_SECRETS = [s for s in [_jwt, _JWT_PREVIOUS] if s]
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30

VAPID_PRIVATE_KEY = _vapid_priv
VAPID_PUBLIC_KEY = _vapid_pub
VAPID_CLAIMS = {"sub": "mailto:admin@localhost"}

SERVER_EPOCH = secrets.token_urlsafe(16)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "https://localhost:8111,http://localhost:8111").split(",") if origin.strip()]
