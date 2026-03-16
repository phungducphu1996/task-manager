from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import LOCAL_TIMEZONE_OFFSET_HOURS
from app.models import STATUS_DESIGN, STATUS_IDEA, STATUS_POSTED, STATUS_READY, TYPE_POST, TYPE_REEL, TYPE_STORY

LOCAL_TZ = timezone(timedelta(hours=LOCAL_TIMEZONE_OFFSET_HOURS))
STATUS_RANK = {
    STATUS_IDEA: 0,
    STATUS_DESIGN: 1,
    STATUS_READY: 2,
    STATUS_POSTED: 3,
}


@dataclass
class ValidationResult:
    ok: bool
    missing_fields: list[str]


def ensure_localized_air_date(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def can_send_full_post(status: str | None) -> bool:
    if not status:
        return False
    return STATUS_RANK.get(status, -1) >= STATUS_RANK[STATUS_READY]


def normalize_tags(value: list[str] | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value if item and item.strip()]


def validate_task(task, campaign_requires_product_url: bool = False) -> ValidationResult:
    missing: list[str] = []

    hashtags = normalize_tags(getattr(task, "hashtags", []))
    mentions = normalize_tags(getattr(task, "mentions", []))
    caption = (getattr(task, "caption", None) or "").strip()
    title = (getattr(task, "title", None) or "").strip()
    task_type = (getattr(task, "type", None) or "").strip().lower()
    air_date = getattr(task, "air_date", None)
    assignee_id = getattr(task, "assignee_id", None)
    status = getattr(task, "status", None)
    product_url = (getattr(task, "product_url", None) or "").strip()
    assets = getattr(task, "assets", None) or []

    if not title:
        missing.append("title")
    if not task_type:
        missing.append("type")
    if len(assets) < 1:
        missing.append("media")
    if not air_date:
        missing.append("air_date")
    if not can_send_full_post(status):
        missing.append("status_ready")
    if not assignee_id:
        missing.append("assignee")

    if task_type == TYPE_STORY:
        pass
    elif task_type in {TYPE_REEL, TYPE_POST}:
        if not caption:
            missing.append("caption")
        if not hashtags:
            missing.append("hashtags")
        if not mentions:
            missing.append("mentions")

    if campaign_requires_product_url and not product_url:
        missing.append("product_url")

    return ValidationResult(ok=not missing, missing_fields=missing)
