from __future__ import annotations

import os
from pathlib import Path


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _unquote(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./social_content.db")
DB_SCHEMA = os.getenv("DB_SCHEMA", "").strip()
LOCAL_TIMEZONE_OFFSET_HOURS = int(os.getenv("LOCAL_TIMEZONE_OFFSET_HOURS", "7"))
BOT_OWNER_FALLBACK = os.getenv("BOT_OWNER_FALLBACK", "content-owner")
DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8001/dashboard/tasks").rstrip("/")
PUBLIC_PREVIEW_BASE_URL = os.getenv("PUBLIC_PREVIEW_BASE_URL", "").rstrip("/")
DAILY_DIGEST_HOUR_LOCAL = int(os.getenv("DAILY_DIGEST_HOUR_LOCAL", "9"))
SOCIAL_GROUP_CHAT_ID = os.getenv("SOCIAL_GROUP_CHAT_ID", "").strip()
ETSY_API_BASE_URL = os.getenv("ETSY_API_BASE_URL", "http://127.0.0.1:9000/api/v1").rstrip("/")
ETSY_JWT_SECRET = os.getenv("ETSY_JWT_SECRET", "")
ETSY_JWT_ALGORITHM = os.getenv("ETSY_JWT_ALGORITHM", "HS256")
AUTH_REQUIRED = (os.getenv("AUTH_REQUIRED", "true").strip().lower() == "true")
ZALO_WORKER_URL = os.getenv("ZALO_WORKER_URL", "").rstrip("/")
ZALO_SHARED_SECRET = os.getenv("ZALO_SHARED_SECRET", "")
ADMIN_BOOTSTRAP_USERNAME = os.getenv("ADMIN_BOOTSTRAP_USERNAME", "").strip()
ADMIN_BOOTSTRAP_PASSWORD = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "")
ADMIN_BOOTSTRAP_NAME = os.getenv("ADMIN_BOOTSTRAP_NAME", "").strip()
