import os
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _BASE / "messenger.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{_DB_PATH.as_posix()}")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
