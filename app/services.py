from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.jobs import schedule_task_jobs
from app.models import (
    Campaign,
    Collection,
    HashtagEntry,
    HashtagGroup,
    SocialAsset,
    SocialTask,
    TaskCollectionLink,
    TaskActivityLog,
    TaskChecklistItem,
    TaskComment,
    User,
)
from app.schemas import Base64MediaFileIn, ChecklistUpdateRequest, TaskCreate, TaskUpdate
from app.validation import LOCAL_TZ, ensure_localized_air_date, validate_task

DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://localhost:8001/dashboard/tasks")
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_CAMPAIGN_COLOR = "#d8d2bc"
DEFAULT_CAMPAIGN_ICON = "📌"


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    localized = ensure_localized_air_date(value)
    if not localized:
        return None
    return localized.astimezone(timezone.utc)


def _to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _detect_asset_kind(url: str) -> str:
    lowered = url.lower()
    if lowered.endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
        return "video"
    return "image"


def _is_demo_asset_url(url: str | None) -> bool:
    return "cdn.example.com" in str(url or "").lower()


def _pick_preview_image_url(task: SocialTask) -> str | None:
    if not task.assets:
        return None
    real_image = next((asset for asset in task.assets if asset.kind == "image" and not _is_demo_asset_url(asset.url)), None)
    if real_image:
        return real_image.url
    any_image = next((asset for asset in task.assets if asset.kind == "image"), None)
    if any_image:
        return any_image.url
    return task.assets[0].url


def _normalize_campaign_color(value: str | None) -> str | None:
    if value is None:
        return None
    clean = str(value).strip().lower()
    if not clean:
        return None
    return clean if HEX_COLOR_RE.fullmatch(clean) else None


def _normalize_campaign_icon(value: str | None) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    return clean[:16]


def _ext_from_content_type(content_type: str | None) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }
    return mapping.get(str(content_type or "").lower(), "")


def _save_base64_media_file(item: Base64MediaFileIn) -> tuple[str, str, str]:
    payload = str(item.data_base64 or "").strip()
    if not payload:
        raise ValueError("empty_media_payload")
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid_media_payload") from exc

    if not raw:
        raise ValueError("empty_media_payload")

    original_name = str(item.filename or "").strip()
    suffix = Path(original_name).suffix.lower() if original_name else ""
    if not suffix:
        suffix = _ext_from_content_type(item.content_type)
    kind = _detect_asset_kind(f"file{suffix}") if suffix else ("video" if str(item.content_type or "").startswith("video/") else "image")

    stored_name = f"{uuid4().hex}{suffix}"
    file_path = UPLOADS_DIR / stored_name
    file_path.write_bytes(raw)

    public_url = f"/media/{stored_name}"
    return kind, str(file_path), public_url


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _normalize_hashtag(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if not clean.startswith("#"):
        clean = f"#{clean}"
    return clean.lower()


def log_activity(
    db: Session,
    task_id: str,
    action: str,
    actor_id: str | None = None,
    field_name: str | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
) -> None:
    db.add(
        TaskActivityLog(
            task_id=task_id,
            actor_id=actor_id,
            action=action,
            field_name=field_name,
            old_value=_serialize(old_value),
            new_value=_serialize(new_value),
        )
    )


def _normalize_username(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    return cleaned


def _normalize_role(value: str | None, fallback: str = "content") -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return fallback
    return cleaned[:60]


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, salt, hex_digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    expected = bytes.fromhex(hex_digest)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return hmac.compare_digest(actual, expected)


def _resolve_user_for_auth(db: Session, username: str) -> User | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    return (
        db.execute(select(User).where(func.lower(User.username) == normalized))
        .scalars()
        .first()
    )


def get_or_create_user(db: Session, name: str | None, zalo_user_id: str | None = None) -> User | None:
    if not name and not zalo_user_id:
        return None

    statement = select(User)
    if zalo_user_id:
        statement = statement.where(User.zalo_user_id == zalo_user_id)
    else:
        clean_name = name.strip()
        statement = statement.where(func.lower(User.name) == clean_name.lower())

    user = db.execute(statement).scalars().first()
    if user:
        if zalo_user_id and not user.zalo_user_id:
            user.zalo_user_id = zalo_user_id
        if not user.is_active:
            user.is_active = True
        return user

    safe_name = (name or zalo_user_id or "unknown").strip()[:120]
    normalized_username = _normalize_username(safe_name.replace(" ", "."))
    unique_username = normalized_username
    if unique_username:
        suffix = 1
        while db.execute(select(User).where(func.lower(User.username) == unique_username)).scalars().first():
            unique_username = f"{normalized_username}.{suffix}"
            suffix += 1
    user = User(
        name=safe_name,
        username=unique_username,
        role="content",
        is_active=True,
        zalo_user_id=zalo_user_id,
    )
    db.add(user)
    db.flush()
    return user


def authenticate_local_user(db: Session, username: str, password: str) -> User | None:
    user = _resolve_user_for_auth(db, username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def list_users(db: Session, include_inactive: bool = False) -> list[User]:
    query = select(User)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    return db.execute(query.order_by(User.name.asc())).scalars().all()


def get_user_by_id(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise ValueError("user_not_found")
    return user


def create_user(
    db: Session,
    *,
    name: str,
    username: str,
    role: str = "content",
    avatar_url: str | None = None,
    password: str,
    is_active: bool = True,
) -> User:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("user_name_required")
    clean_username = _normalize_username(username)
    if not clean_username:
        raise ValueError("username_required")
    if db.execute(select(User).where(func.lower(User.username) == clean_username)).scalars().first():
        raise ValueError("username_exists")
    if db.execute(select(User).where(func.lower(User.name) == clean_name.lower())).scalars().first():
        raise ValueError("user_name_exists")
    user = User(
        name=clean_name[:120],
        username=clean_username[:120],
        role=_normalize_role(role),
        avatar_url=(avatar_url or "").strip() or None,
        password_hash=_hash_password(password),
        is_active=bool(is_active),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user_id: str,
    *,
    name: str | None = None,
    username: str | None = None,
    role: str | None = None,
    avatar_url: str | None = None,
    is_active: bool | None = None,
) -> User:
    user = get_user_by_id(db, user_id)

    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("user_name_required")
        duplicate = (
            db.execute(select(User).where(func.lower(User.name) == clean_name.lower(), User.id != user_id))
            .scalars()
            .first()
        )
        if duplicate:
            raise ValueError("user_name_exists")
        user.name = clean_name[:120]

    if username is not None:
        clean_username = _normalize_username(username)
        if not clean_username:
            raise ValueError("username_required")
        duplicate = (
            db.execute(select(User).where(func.lower(User.username) == clean_username, User.id != user_id))
            .scalars()
            .first()
        )
        if duplicate:
            raise ValueError("username_exists")
        user.username = clean_username[:120]

    if role is not None:
        user.role = _normalize_role(role, fallback=user.role or "content")

    if avatar_url is not None:
        user.avatar_url = avatar_url.strip() or None

    if is_active is not None:
        user.is_active = bool(is_active)

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: str) -> User:
    user = get_user_by_id(db, user_id)
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


def set_user_password(db: Session, user_id: str, password: str) -> User:
    user = get_user_by_id(db, user_id)
    user.password_hash = _hash_password(password)
    db.commit()
    db.refresh(user)
    return user


def set_user_avatar(db: Session, user_id: str, file: Base64MediaFileIn) -> User:
    user = get_user_by_id(db, user_id)
    kind, _storage_path, url = _save_base64_media_file(file)
    if kind != "image":
        raise ValueError("avatar_must_be_image")
    user.avatar_url = url
    db.commit()
    db.refresh(user)
    return user


def get_user_by_principal(db: Session, principal_user_id: str, principal_username: str) -> User | None:
    by_id = db.get(User, principal_user_id) if principal_user_id else None
    if by_id:
        return by_id
    normalized_username = _normalize_username(principal_username)
    if not normalized_username:
        return None
    return (
        db.execute(select(User).where(func.lower(User.username) == normalized_username))
        .scalars()
        .first()
    )


def ensure_principal_user(
    db: Session,
    *,
    principal_user_id: str,
    principal_username: str,
    role: str,
    name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    user = get_user_by_principal(db, principal_user_id, principal_username)
    if user:
        changed = False
        normalized_username = _normalize_username(principal_username)
        if normalized_username and user.username != normalized_username:
            duplicate = (
                db.execute(select(User).where(func.lower(User.username) == normalized_username, User.id != user.id))
                .scalars()
                .first()
            )
            if not duplicate:
                user.username = normalized_username
                changed = True
        if name and user.name != name:
            user.name = name[:120]
            changed = True
        normalized_role = _normalize_role(role, fallback=user.role or "content")
        if user.role != normalized_role:
            user.role = normalized_role
            changed = True
        if avatar_url is not None and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if changed:
            db.commit()
            db.refresh(user)
        return user

    safe_name = (name or principal_username or "User").strip()[:120]
    normalized_username = _normalize_username(principal_username) or _normalize_username(safe_name) or None
    payload: dict[str, Any] = {
        "name": safe_name,
        "username": normalized_username,
        "role": _normalize_role(role),
        "avatar_url": avatar_url,
        "is_active": True,
    }
    if principal_user_id:
        payload["id"] = principal_user_id
    user = User(**payload)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_my_profile(
    db: Session,
    *,
    user_id: str,
    name: str | None = None,
    username: str | None = None,
    avatar_url: str | None = None,
) -> User:
    return update_user(db, user_id, name=name, username=username, avatar_url=avatar_url)


def change_my_password(
    db: Session,
    *,
    user_id: str,
    current_password: str,
    new_password: str,
) -> User:
    user = get_user_by_id(db, user_id)
    if user.password_hash and not verify_password(current_password, user.password_hash):
        raise ValueError("current_password_invalid")
    user.password_hash = _hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_campaign(
    db: Session,
    campaign_name: str | None,
    requires_product_url: bool | None = None,
) -> Campaign | None:
    if not campaign_name:
        return None
    campaign = (
        db.execute(select(Campaign).where(func.lower(Campaign.name) == campaign_name.lower()))
        .scalars()
        .first()
    )
    if campaign:
        if requires_product_url is not None:
            campaign.requires_product_url = requires_product_url
        return campaign

    campaign = Campaign(name=campaign_name, requires_product_url=bool(requires_product_url))
    db.add(campaign)
    db.flush()
    return campaign


def _replace_task_collections(db: Session, task: SocialTask, collection_ids: list[str], actor_id: str | None = None) -> None:
    requested_ids = {collection_id.strip() for collection_id in collection_ids if collection_id and collection_id.strip()}
    current_ids = {collection.id for collection in task.collections}

    for link in db.execute(select(TaskCollectionLink).where(TaskCollectionLink.task_id == task.id)).scalars().all():
        if link.collection_id not in requested_ids:
            db.delete(link)

    for collection_id in requested_ids:
        if collection_id in current_ids:
            continue
        collection = db.get(Collection, collection_id)
        if not collection:
            continue
        db.add(TaskCollectionLink(task_id=task.id, collection_id=collection_id))

    if requested_ids != current_ids:
        log_activity(
            db,
            task.id,
            action="task_updated",
            actor_id=actor_id,
            field_name="collections",
            old_value=sorted(current_ids),
            new_value=sorted(requested_ids),
        )


def _track_hashtag_usage(db: Session, tags: list[str], campaign_id: str | None, task_type: str | None) -> None:
    normalized_tags: list[str] = []
    for tag in tags:
        normalized = _normalize_hashtag(tag)
        if normalized:
            normalized_tags.append(normalized)
    if not normalized_tags:
        return

    group_rows = (
        db.execute(select(HashtagGroup).where(HashtagGroup.is_active.is_(True)))
        .scalars()
        .all()
    )
    groups_by_scope: dict[str, HashtagGroup] = {}
    for group in group_rows:
        if group.scope == "global":
            groups_by_scope.setdefault("global", group)
        if group.scope == "campaign" and campaign_id and group.campaign_id == campaign_id:
            groups_by_scope.setdefault("campaign", group)
        if group.scope == "type" and task_type and group.task_type == task_type:
            groups_by_scope.setdefault("type", group)

    fallback_group = groups_by_scope.get("campaign") or groups_by_scope.get("type") or groups_by_scope.get("global")
    if not fallback_group:
        fallback_group = HashtagGroup(name="Global Hashtags", scope="global", is_active=True)
        db.add(fallback_group)
        db.flush()

    now = datetime.now(timezone.utc)
    for normalized in normalized_tags:
        matched = (
            db.execute(
                select(HashtagEntry).where(
                    HashtagEntry.group_id == fallback_group.id,
                    HashtagEntry.normalized_tag == normalized,
                )
            )
            .scalars()
            .first()
        )
        if not matched:
            matched = HashtagEntry(
                group_id=fallback_group.id,
                tag=normalized,
                normalized_tag=normalized,
                is_active=True,
                usage_count=0,
            )
            db.add(matched)
        matched.usage_count = int(matched.usage_count or 0) + 1
        matched.last_used_at = now


def _attach_assets(db: Session, task: SocialTask, media_urls: list[str], actor_id: str | None = None) -> None:
    for media_url in media_urls:
        clean_url = media_url.strip()
        if not clean_url:
            continue
        db.add(
            SocialAsset(
                task_id=task.id,
                kind=_detect_asset_kind(clean_url),
                storage_path=clean_url,
                url=clean_url,
            )
        )
        log_activity(db, task.id, action="asset_attached", actor_id=actor_id, new_value=clean_url)


def _normalize_quick_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:256]


def create_task(db: Session, payload: TaskCreate) -> SocialTask:
    assignee = get_or_create_user(db, payload.assignee_name)
    creator = get_or_create_user(db, payload.created_by_name) if payload.created_by_name else None
    campaign = get_or_create_campaign(db, payload.campaign_name, payload.campaign_requires_product_url)

    task = SocialTask(
        brand=payload.brand,
        platform=payload.platform,
        type=payload.type.value,
        title=payload.title,
        quick_note=_normalize_quick_note(payload.quick_note),
        caption=payload.caption,
        hashtags=payload.hashtags,
        mentions=payload.mentions,
        product_url=payload.product_url,
        campaign_id=campaign.id if campaign else None,
        air_date=_to_utc(payload.air_date),
        status=payload.status.value,
        assignee_id=assignee.id if assignee else None,
        created_by=creator.id if creator else None,
    )
    db.add(task)
    db.flush()

    for item in payload.checklist:
        db.add(
            TaskChecklistItem(
                task_id=task.id,
                title=item.title,
                is_done=item.is_done,
                position=item.position,
            )
        )

    _attach_assets(db, task, payload.media_urls, creator.id if creator else None)
    if payload.collection_ids:
        _replace_task_collections(db, task, payload.collection_ids, creator.id if creator else None)
    _track_hashtag_usage(db, payload.hashtags, task.campaign_id, task.type)
    log_activity(db, task.id, action="task_created", actor_id=creator.id if creator else None)

    if task.air_date:
        schedule_task_jobs(db, task)

    db.commit()
    return get_task_by_id(db, task.id)


def get_task_by_id(db: Session, task_id: str) -> SocialTask:
    task = (
        db.execute(
            select(SocialTask)
            .where(SocialTask.id == task_id)
            .options(
                joinedload(SocialTask.assets),
                joinedload(SocialTask.comments),
                joinedload(SocialTask.checklist_items),
                joinedload(SocialTask.activity_logs),
                joinedload(SocialTask.campaign),
                joinedload(SocialTask.assignee),
                joinedload(SocialTask.collections),
            )
        )
        .scalars()
        .first()
    )
    if not task:
        raise ValueError("task_not_found")
    return task


def list_tasks(
    db: Session,
    status: str | None = None,
    assignee_id: str | None = None,
    campaign_id: str | None = None,
    collection_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SocialTask]:
    query = select(SocialTask).options(
        joinedload(SocialTask.assets),
        joinedload(SocialTask.assignee),
        joinedload(SocialTask.campaign),
        joinedload(SocialTask.collections),
    )

    if status:
        query = query.where(SocialTask.status == status)
    if assignee_id:
        query = query.where(SocialTask.assignee_id == assignee_id)
    if campaign_id:
        query = query.where(SocialTask.campaign_id == campaign_id)
    if collection_id:
        query = query.join(TaskCollectionLink, TaskCollectionLink.task_id == SocialTask.id).where(
            TaskCollectionLink.collection_id == collection_id
        )
    if date_from:
        query = query.where(SocialTask.air_date >= _to_utc(date_from))
    if date_to:
        query = query.where(SocialTask.air_date <= _to_utc(date_to))

    return db.execute(query.order_by(SocialTask.air_date.asc())).scalars().unique().all()


def update_task(db: Session, task_id: str, payload: TaskUpdate, actor_name: str | None = None) -> SocialTask:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None
    actor_id = actor.id if actor else None

    changed_air_date = False

    def update_field(field_name: str, new_value: Any):
        old_value = getattr(task, field_name)
        if old_value != new_value:
            setattr(task, field_name, new_value)
            log_activity(
                db,
                task.id,
                action="task_updated",
                actor_id=actor_id,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
            )

    if payload.title is not None:
        update_field("title", payload.title)
    if payload.type is not None:
        update_field("type", payload.type.value)
    if payload.caption is not None:
        update_field("caption", payload.caption)
    if payload.quick_note is not None:
        update_field("quick_note", _normalize_quick_note(payload.quick_note))
    if payload.hashtags is not None:
        update_field("hashtags", payload.hashtags)
    if payload.mentions is not None:
        update_field("mentions", payload.mentions)
    if payload.product_url is not None:
        update_field("product_url", payload.product_url)
    if payload.status is not None:
        update_field("status", payload.status.value)
    if payload.brand is not None:
        update_field("brand", payload.brand)
    if payload.platform is not None:
        update_field("platform", payload.platform)

    if payload.air_date is not None:
        normalized = _to_utc(payload.air_date)
        if task.air_date != normalized:
            update_field("air_date", normalized)
            changed_air_date = True

    if payload.assignee_name is not None:
        assignee = get_or_create_user(db, payload.assignee_name)
        update_field("assignee_id", assignee.id if assignee else None)

    if payload.campaign_name is not None:
        campaign = get_or_create_campaign(db, payload.campaign_name, payload.campaign_requires_product_url)
        update_field("campaign_id", campaign.id if campaign else None)
    elif payload.campaign_requires_product_url is not None and task.campaign_id:
        campaign = db.get(Campaign, task.campaign_id)
        if campaign:
            campaign.requires_product_url = payload.campaign_requires_product_url

    if payload.collection_ids is not None:
        _replace_task_collections(db, task, payload.collection_ids, actor_id)

    if payload.hashtags is not None:
        _track_hashtag_usage(db, payload.hashtags, task.campaign_id, task.type)

    if changed_air_date and task.air_date:
        schedule_task_jobs(db, task)

    db.commit()
    return get_task_by_id(db, task.id)


def delete_task(db: Session, task_id: str, actor_name: str | None = None) -> None:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None
    log_activity(db, task.id, action="task_deleted", actor_id=actor.id if actor else None)
    db.delete(task)
    db.commit()


def add_assets(db: Session, task_id: str, media_urls: list[str], actor_name: str | None = None) -> SocialTask:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None
    _attach_assets(db, task, media_urls, actor.id if actor else None)
    db.commit()
    return get_task_by_id(db, task.id)


def add_base64_assets(
    db: Session,
    task_id: str,
    files: list[Base64MediaFileIn],
    actor_name: str | None = None,
) -> SocialTask:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None
    actor_id = actor.id if actor else None

    for item in files:
        kind, storage_path, url = _save_base64_media_file(item)
        db.add(
            SocialAsset(
                task_id=task.id,
                kind=kind,
                storage_path=storage_path,
                url=url,
            )
        )
        log_activity(db, task.id, action="asset_uploaded", actor_id=actor_id, new_value=url)

    db.commit()
    return get_task_by_id(db, task.id)


def delete_asset(
    db: Session,
    task_id: str,
    asset_id: str,
    actor_name: str | None = None,
) -> SocialTask:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None
    actor_id = actor.id if actor else None

    asset = next((item for item in task.assets if item.id == asset_id), None)
    if not asset:
        raise ValueError("asset_not_found")

    storage_path = str(asset.storage_path or "").strip()
    if storage_path:
        path = Path(storage_path)
        if path.exists() and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass

    old_url = asset.url
    db.delete(asset)
    log_activity(
        db,
        task.id,
        action="asset_deleted",
        actor_id=actor_id,
        field_name="asset",
        old_value=old_url,
    )
    db.commit()
    return get_task_by_id(db, task.id)


def add_comment(
    db: Session,
    task_id: str,
    content: str,
    user_name: str | None = None,
    parent_id: str | None = None,
) -> TaskComment:
    task = get_task_by_id(db, task_id)
    user = get_or_create_user(db, user_name) if user_name else None
    comment = TaskComment(task_id=task.id, user_id=user.id if user else None, content=content, parent_id=parent_id)
    db.add(comment)
    log_activity(
        db,
        task.id,
        action="comment_added",
        actor_id=user.id if user else None,
        field_name="comment",
        new_value=content,
    )
    db.commit()
    db.refresh(comment)
    return comment


def replace_checklist(
    db: Session,
    task_id: str,
    payload: ChecklistUpdateRequest,
    actor_name: str | None = None,
) -> SocialTask:
    task = get_task_by_id(db, task_id)
    actor = get_or_create_user(db, actor_name) if actor_name else None

    for item in list(task.checklist_items):
        db.delete(item)

    for raw in payload.items:
        db.add(
            TaskChecklistItem(
                task_id=task.id,
                title=raw.title,
                is_done=raw.is_done,
                position=raw.position,
            )
        )

    log_activity(
        db,
        task.id,
        action="checklist_replaced",
        actor_id=actor.id if actor else None,
        field_name="checklist",
        new_value=[item.title for item in payload.items],
    )
    db.commit()
    return get_task_by_id(db, task.id)


def validate_for_task(task: SocialTask):
    campaign_requires_url = bool(task.campaign and task.campaign.requires_product_url)
    return validate_task(task, campaign_requires_url)


def dashboard_link(task_id: str) -> str:
    return f"{DASHBOARD_BASE_URL}/{task_id}"


def analytics_basic(db: Session) -> dict:
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(LOCAL_TZ)
    start_of_week = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_of_week.astimezone(timezone.utc)

    total_this_week = (
        db.execute(select(func.count()).select_from(SocialTask).where(SocialTask.air_date >= start_utc))
        .scalar_one()
    )

    overdue_count = (
        db.execute(
            select(func.count())
            .select_from(SocialTask)
            .where(SocialTask.air_date < now_utc, SocialTask.status != "posted")
        )
        .scalar_one()
    )

    campaign_count = db.execute(select(func.count()).select_from(Campaign)).scalar_one()

    top_rows = (
        db.execute(
            select(User.name, func.count(SocialTask.id).label("task_count"))
            .join(SocialTask, SocialTask.assignee_id == User.id)
            .group_by(User.name)
            .order_by(func.count(SocialTask.id).desc())
            .limit(5)
        )
        .all()
    )
    top_assignees = [{"name": name, "task_count": int(count)} for name, count in top_rows]

    return {
        "total_this_week": int(total_this_week),
        "overdue_count": int(overdue_count),
        "campaign_count": int(campaign_count),
        "top_assignees": top_assignees,
    }


def task_summary(task: SocialTask) -> dict:
    validation = validate_for_task(task)
    thumbnail = _pick_preview_image_url(task)
    caption_done = bool((task.caption or "").strip())
    hashtag_done = bool(task.hashtags)
    media_done = bool(task.assets)
    return {
        "id": task.id,
        "title": task.title,
        "quick_note": task.quick_note,
        "type": task.type,
        "air_date": _to_local(task.air_date),
        "status": task.status,
        "assignee": task.assignee.name if task.assignee else None,
        "campaign": task.campaign.name if task.campaign else None,
        "campaign_color": task.campaign.color if task.campaign and task.campaign.color else None,
        "campaign_icon": task.campaign.icon if task.campaign and task.campaign.icon else None,
        "collections": [collection.name for collection in sorted(task.collections, key=lambda c: c.name.lower())],
        "missing_count": len(validation.missing_fields),
        "missing_fields": validation.missing_fields,
        "media_thumbnail": thumbnail,
        "caption_done": caption_done,
        "hashtag_done": hashtag_done,
        "media_done": media_done,
    }


def kanban_view(db: Session) -> dict:
    tasks = (
        db.execute(
            select(SocialTask).options(
                joinedload(SocialTask.assets),
                joinedload(SocialTask.assignee),
                joinedload(SocialTask.campaign),
                joinedload(SocialTask.collections),
            )
        )
        .scalars()
        .unique()
        .all()
    )
    columns = {"idea": [], "design": [], "ready": [], "posted": []}
    for task in tasks:
        bucket = task.status if task.status in columns else "idea"
        columns[bucket].append(task_summary(task))
    return columns


def calendar_view(
    db: Session,
    platform: str | None = None,
    assignee_id: str | None = None,
    campaign_id: str | None = None,
) -> list[dict]:
    query = (
        select(SocialTask)
        .options(joinedload(SocialTask.assignee), joinedload(SocialTask.campaign), joinedload(SocialTask.assets))
        .where(SocialTask.air_date.is_not(None))
    )
    if platform:
        query = query.where(SocialTask.platform == platform)
    if assignee_id:
        query = query.where(SocialTask.assignee_id == assignee_id)
    if campaign_id:
        query = query.where(SocialTask.campaign_id == campaign_id)

    tasks = db.execute(query.order_by(SocialTask.air_date.asc())).scalars().unique().all()
    return [
        {
            "id": task.id,
            "title": task.title,
            "quick_note": task.quick_note,
            "type": task.type,
            "status": task.status,
            "air_date": _to_local(task.air_date),
            "assignee": task.assignee.name if task.assignee else None,
            "campaign": task.campaign.name if task.campaign else None,
            "campaign_color": task.campaign.color if task.campaign and task.campaign.color else None,
            "campaign_icon": task.campaign.icon if task.campaign and task.campaign.icon else None,
            "platform": task.platform,
            "media_thumbnail": _pick_preview_image_url(task),
        }
        for task in tasks
    ]


def task_to_response(task: SocialTask) -> dict:
    validation = validate_for_task(task)
    return {
        "id": task.id,
        "brand": task.brand,
        "platform": task.platform,
        "type": task.type,
        "title": task.title,
        "quick_note": task.quick_note,
        "caption": task.caption,
        "hashtags": task.hashtags or [],
        "mentions": task.mentions or [],
        "product_url": task.product_url,
        "campaign_id": task.campaign_id,
        "air_date": _to_local(task.air_date),
        "status": task.status,
        "assignee_id": task.assignee_id,
        "assignee_name": task.assignee.name if task.assignee else None,
        "campaign_name": task.campaign.name if task.campaign else None,
        "campaign_color": task.campaign.color if task.campaign and task.campaign.color else None,
        "campaign_icon": task.campaign.icon if task.campaign and task.campaign.icon else None,
        "created_by": task.created_by,
        "created_at": _to_local(task.created_at),
        "updated_at": _to_local(task.updated_at),
        "collections": sorted(task.collections, key=lambda collection: collection.name.lower()),
        "assets": task.assets,
        "comments": sorted(task.comments, key=lambda c: c.created_at),
        "checklist_items": sorted(task.checklist_items, key=lambda item: item.position),
        "activity_logs": sorted(task.activity_logs, key=lambda log: log.created_at),
        "validate": {"ok": validation.ok, "missing_fields": validation.missing_fields},
    }


def list_collections(db: Session) -> list[Collection]:
    return (
        db.execute(select(Collection).order_by(Collection.name.asc()))
        .scalars()
        .all()
    )


def create_collection(
    db: Session,
    name: str,
    description: str | None = None,
    color: str | None = None,
    is_active: bool = True,
) -> Collection:
    existing = db.execute(select(Collection).where(func.lower(Collection.name) == name.lower())).scalars().first()
    if existing:
        raise ValueError("collection_name_exists")
    collection = Collection(name=name.strip(), description=description, color=color, is_active=is_active)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def update_collection(
    db: Session,
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    color: str | None = None,
    is_active: bool | None = None,
) -> Collection:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise ValueError("collection_not_found")
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("collection_name_required")
        existing = db.execute(
            select(Collection).where(func.lower(Collection.name) == clean_name.lower(), Collection.id != collection_id)
        ).scalars().first()
        if existing:
            raise ValueError("collection_name_exists")
        collection.name = clean_name
    if description is not None:
        collection.description = description
    if color is not None:
        collection.color = color
    if is_active is not None:
        collection.is_active = is_active
    db.commit()
    db.refresh(collection)
    return collection


def delete_collection(db: Session, collection_id: str) -> None:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise ValueError("collection_not_found")
    db.delete(collection)
    db.commit()


def add_tasks_to_collection(db: Session, collection_id: str, task_ids: list[str]) -> Collection:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise ValueError("collection_not_found")
    task_id_set = {task_id.strip() for task_id in task_ids if task_id and task_id.strip()}
    if not task_id_set:
        return collection
    tasks = db.execute(select(SocialTask).where(SocialTask.id.in_(task_id_set))).scalars().all()
    existing_links = db.execute(select(TaskCollectionLink).where(TaskCollectionLink.collection_id == collection_id)).scalars().all()
    existing_task_ids = {link.task_id for link in existing_links}
    for task in tasks:
        if task.id in existing_task_ids:
            continue
        db.add(TaskCollectionLink(task_id=task.id, collection_id=collection_id))
    db.commit()
    db.refresh(collection)
    return collection


def remove_task_from_collection(db: Session, collection_id: str, task_id: str) -> None:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise ValueError("collection_not_found")
    link = db.execute(
        select(TaskCollectionLink).where(
            TaskCollectionLink.collection_id == collection_id,
            TaskCollectionLink.task_id == task_id,
        )
    ).scalars().first()
    if link:
        db.delete(link)
        db.commit()


def _resolve_campaign_id(db: Session, campaign_name: str | None) -> str | None:
    if not campaign_name:
        return None
    campaign = db.execute(select(Campaign).where(func.lower(Campaign.name) == campaign_name.lower())).scalars().first()
    return campaign.id if campaign else None


def list_campaigns(db: Session) -> list[Campaign]:
    return db.execute(select(Campaign).order_by(Campaign.created_at.desc(), Campaign.name.asc())).scalars().all()


def create_campaign(
    db: Session,
    name: str,
    status: str = "planning",
    start_date: str | None = None,
    end_date: str | None = None,
    description: str | None = None,
    link_url: str | None = None,
    color: str | None = None,
    icon: str | None = None,
    requires_product_url: bool = False,
    brand: str | None = None,
    platform: str | None = None,
) -> Campaign:
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("campaign_name_required")
    existing = db.execute(select(Campaign).where(func.lower(Campaign.name) == clean_name.lower())).scalars().first()
    if existing:
        raise ValueError("campaign_name_exists")
    campaign = Campaign(
        name=clean_name,
        status=(status or "planning").strip().lower() or "planning",
        start_date=start_date.strip() if start_date else None,
        end_date=end_date.strip() if end_date else None,
        description=description.strip() if description else None,
        link_url=link_url.strip() if link_url else None,
        color=_normalize_campaign_color(color) or DEFAULT_CAMPAIGN_COLOR,
        icon=_normalize_campaign_icon(icon) or DEFAULT_CAMPAIGN_ICON,
        requires_product_url=bool(requires_product_url),
        brand=brand.strip() if brand else None,
        platform=platform.strip() if platform else None,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def update_campaign(
    db: Session,
    campaign_id: str,
    name: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    description: str | None = None,
    link_url: str | None = None,
    color: str | None = None,
    icon: str | None = None,
    requires_product_url: bool | None = None,
    brand: str | None = None,
    platform: str | None = None,
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("campaign_not_found")
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("campaign_name_required")
        existing = db.execute(
            select(Campaign).where(func.lower(Campaign.name) == clean_name.lower(), Campaign.id != campaign_id)
        ).scalars().first()
        if existing:
            raise ValueError("campaign_name_exists")
        campaign.name = clean_name
    if status is not None:
        campaign.status = (status or "planning").strip().lower() or "planning"
    if start_date is not None:
        campaign.start_date = start_date.strip() if start_date else None
    if end_date is not None:
        campaign.end_date = end_date.strip() if end_date else None
    if description is not None:
        campaign.description = description.strip() if description else None
    if link_url is not None:
        campaign.link_url = link_url.strip() if link_url else None
    if color is not None:
        campaign.color = _normalize_campaign_color(color) or DEFAULT_CAMPAIGN_COLOR
    if icon is not None:
        campaign.icon = _normalize_campaign_icon(icon) or DEFAULT_CAMPAIGN_ICON
    if requires_product_url is not None:
        campaign.requires_product_url = bool(requires_product_url)
    if brand is not None:
        campaign.brand = brand.strip() if brand else None
    if platform is not None:
        campaign.platform = platform.strip() if platform else None
    db.commit()
    db.refresh(campaign)
    return campaign


def delete_campaign(db: Session, campaign_id: str) -> None:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("campaign_not_found")
    tasks = db.execute(select(SocialTask).where(SocialTask.campaign_id == campaign_id)).scalars().all()
    for task in tasks:
        task.campaign_id = None
    db.delete(campaign)
    db.commit()


def list_hashtag_groups(db: Session) -> list[HashtagGroup]:
    return db.execute(select(HashtagGroup).order_by(HashtagGroup.name.asc())).scalars().all()


def create_hashtag_group(
    db: Session,
    name: str,
    scope: str,
    campaign_name: str | None = None,
    task_type: str | None = None,
    is_active: bool = True,
) -> HashtagGroup:
    normalized_scope = (scope or "global").strip().lower()
    if normalized_scope not in {"global", "campaign", "type"}:
        raise ValueError("invalid_hashtag_scope")
    existing = db.execute(select(HashtagGroup).where(func.lower(HashtagGroup.name) == name.lower())).scalars().first()
    if existing:
        raise ValueError("hashtag_group_name_exists")
    campaign_id = _resolve_campaign_id(db, campaign_name) if normalized_scope == "campaign" else None
    group = HashtagGroup(
        name=name.strip(),
        scope=normalized_scope,
        campaign_id=campaign_id,
        task_type=task_type.lower() if task_type else None,
        is_active=is_active,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_hashtag_group(
    db: Session,
    group_id: str,
    name: str | None = None,
    scope: str | None = None,
    campaign_name: str | None = None,
    task_type: str | None = None,
    is_active: bool | None = None,
) -> HashtagGroup:
    group = db.get(HashtagGroup, group_id)
    if not group:
        raise ValueError("hashtag_group_not_found")
    if name is not None:
        clean = name.strip()
        if not clean:
            raise ValueError("hashtag_group_name_required")
        existing = db.execute(
            select(HashtagGroup).where(func.lower(HashtagGroup.name) == clean.lower(), HashtagGroup.id != group_id)
        ).scalars().first()
        if existing:
            raise ValueError("hashtag_group_name_exists")
        group.name = clean
    if scope is not None:
        normalized_scope = scope.strip().lower()
        if normalized_scope not in {"global", "campaign", "type"}:
            raise ValueError("invalid_hashtag_scope")
        group.scope = normalized_scope
    if campaign_name is not None:
        group.campaign_id = _resolve_campaign_id(db, campaign_name) if campaign_name else None
    if task_type is not None:
        group.task_type = task_type.lower() if task_type else None
    if is_active is not None:
        group.is_active = is_active
    db.commit()
    db.refresh(group)
    return group


def delete_hashtag_group(db: Session, group_id: str) -> None:
    group = db.get(HashtagGroup, group_id)
    if not group:
        raise ValueError("hashtag_group_not_found")
    db.delete(group)
    db.commit()


def list_hashtags(
    db: Session,
    group_id: str | None = None,
    q: str | None = None,
    is_active: bool | None = None,
) -> list[HashtagEntry]:
    query = select(HashtagEntry)
    if group_id:
        query = query.where(HashtagEntry.group_id == group_id)
    if q:
        query = query.where(func.lower(HashtagEntry.tag).contains(q.lower()))
    if is_active is not None:
        query = query.where(HashtagEntry.is_active == is_active)
    return db.execute(query.order_by(HashtagEntry.usage_count.desc(), HashtagEntry.tag.asc())).scalars().all()


def create_hashtag(db: Session, group_id: str, tag: str, is_active: bool = True) -> HashtagEntry:
    group = db.get(HashtagGroup, group_id)
    if not group:
        raise ValueError("hashtag_group_not_found")
    normalized = _normalize_hashtag(tag)
    if not normalized:
        raise ValueError("invalid_hashtag_tag")
    existing = db.execute(
        select(HashtagEntry).where(
            HashtagEntry.group_id == group_id,
            HashtagEntry.normalized_tag == normalized,
        )
    ).scalars().first()
    if existing:
        raise ValueError("hashtag_exists")
    entry = HashtagEntry(group_id=group_id, tag=normalized, normalized_tag=normalized, is_active=is_active)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_hashtag(db: Session, hashtag_id: str, tag: str | None = None, is_active: bool | None = None) -> HashtagEntry:
    entry = db.get(HashtagEntry, hashtag_id)
    if not entry:
        raise ValueError("hashtag_not_found")
    if tag is not None:
        normalized = _normalize_hashtag(tag)
        if not normalized:
            raise ValueError("invalid_hashtag_tag")
        dupe = db.execute(
            select(HashtagEntry).where(
                HashtagEntry.group_id == entry.group_id,
                HashtagEntry.normalized_tag == normalized,
                HashtagEntry.id != hashtag_id,
            )
        ).scalars().first()
        if dupe:
            raise ValueError("hashtag_exists")
        entry.tag = normalized
        entry.normalized_tag = normalized
    if is_active is not None:
        entry.is_active = is_active
    db.commit()
    db.refresh(entry)
    return entry


def delete_hashtag(db: Session, hashtag_id: str) -> None:
    entry = db.get(HashtagEntry, hashtag_id)
    if not entry:
        raise ValueError("hashtag_not_found")
    db.delete(entry)
    db.commit()


def suggest_hashtags(
    db: Session,
    campaign_name: str | None = None,
    task_type: str | None = None,
    limit: int = 20,
) -> list[HashtagEntry]:
    limit = max(1, min(limit, 50))
    campaign_id = _resolve_campaign_id(db, campaign_name)

    groups = db.execute(select(HashtagGroup).where(HashtagGroup.is_active.is_(True))).scalars().all()

    prioritized_group_ids: list[str] = []
    for group in groups:
        if group.scope == "campaign" and campaign_id and group.campaign_id == campaign_id:
            prioritized_group_ids.append(group.id)
    for group in groups:
        if group.scope == "type" and task_type and group.task_type == task_type:
            prioritized_group_ids.append(group.id)
    for group in groups:
        if group.scope == "global":
            prioritized_group_ids.append(group.id)

    if not prioritized_group_ids:
        return []

    rows = db.execute(
        select(HashtagEntry)
        .where(
            HashtagEntry.group_id.in_(prioritized_group_ids),
            HashtagEntry.is_active.is_(True),
        )
        .order_by(HashtagEntry.usage_count.desc(), HashtagEntry.last_used_at.desc(), HashtagEntry.tag.asc())
        .limit(limit * 3)
    ).scalars().all()

    deduped: list[HashtagEntry] = []
    seen: set[str] = set()
    for row in rows:
        if row.normalized_tag in seen:
            continue
        seen.add(row.normalized_tag)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped
