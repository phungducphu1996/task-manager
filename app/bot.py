from __future__ import annotations

import shlex
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SocialTask
from app.schemas import BotWebhookRequest, TaskCreate, TaskStatus, TaskType, TaskUpdate
from app.services import (
    add_assets,
    create_task,
    dashboard_link,
    delete_task,
    get_or_create_user,
    get_task_by_id,
    task_to_response,
    update_task,
)


def _tokenize(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _parse_kv(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    kv: dict[str, str] = {}
    positional: list[str] = []
    current_key: str | None = None
    for token in tokens:
        if "=" in token:
            key, value = token.split("=", 1)
            current_key = key.strip().lower()
            kv[current_key] = value.strip()
            continue

        if current_key in {"hashtags", "hashtag"} and token.startswith("#"):
            kv[current_key] = f"{kv[current_key]} {token}".strip()
            continue
        if current_key in {"mentions", "mention"} and token.startswith("@"):
            kv[current_key] = f"{kv[current_key]} {token}".strip()
            continue

        current_key = None
        positional.append(token)
    return kv, positional


def _parse_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split() if item.strip()]


def _parse_air_date(raw: str | None) -> datetime | None:
    if not raw:
        return None

    candidates = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _parse_type(raw: str | None) -> TaskType | None:
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in TaskType.__members__:
        return TaskType[lowered]
    try:
        return TaskType(lowered)
    except ValueError:
        return None


def _parse_status(raw: str | None) -> TaskStatus | None:
    if not raw:
        return None
    lowered = raw.lower()
    try:
        return TaskStatus(lowered)
    except ValueError:
        return None


def _latest_task_for_user(db: Session, user_id: str) -> SocialTask | None:
    return (
        db.execute(
            select(SocialTask)
            .where(SocialTask.created_by == user_id)
            .order_by(SocialTask.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _build_media_hint(task: SocialTask) -> str | None:
    if task.caption and task.caption.strip():
        return None
    campaign_name = task.campaign.name if task.campaign else "campaign"
    hashtags = task.hashtags or [f"#{campaign_name.lower()}"]
    hashtags_line = " ".join(hashtags)
    return (
        f"Hint: caption is empty. Suggested template: "
        f"\"[{campaign_name}] Key message + CTA + link\" | hashtags: {hashtags_line}"
    )


def handle_bot_command(db: Session, req: BotWebhookRequest) -> dict:
    sender = get_or_create_user(db, req.sender_name or req.sender_id, req.sender_id)

    if not req.text:
        if req.media_urls:
            latest = _latest_task_for_user(db, sender.id)
            if not latest:
                return {
                    "message": "No command provided and no latest task to attach media.",
                    "task_id": None,
                    "validate": None,
                    "dashboard_url": None,
                }
            task = add_assets(db, latest.id, req.media_urls, sender.name)
            payload = task_to_response(task)
            hint = _build_media_hint(task)
            message = f"Attached {len(req.media_urls)} media file(s) to latest task {task.id}."
            if hint:
                message = f"{message} {hint}"
            return {
                "message": message,
                "task_id": task.id,
                "validate": payload["validate"],
                "dashboard_url": dashboard_link(task.id),
            }
        return {
            "message": "Empty payload. Send /new, /set, /status, /assign, /delete, or /attach.",
            "task_id": None,
            "validate": None,
            "dashboard_url": None,
        }

    tokens = _tokenize(req.text.strip())
    if not tokens:
        return {
            "message": "Empty command.",
            "task_id": None,
            "validate": None,
            "dashboard_url": None,
        }

    command = tokens[0].lower()
    args = tokens[1:]

    if command == "/new":
        kv, positional = _parse_kv(args)

        task_type = _parse_type(kv.get("type") or (positional[0] if positional else None))
        if not task_type:
            return {
                "message": "Invalid type. Use story/reel/post.",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        campaign_name = kv.get("campaign") or (positional[1] if len(positional) > 1 else None)

        air_date_raw = kv.get("airdate")
        if not air_date_raw and len(positional) > 3:
            air_date_raw = f"{positional[2]} {positional[3]}"
        elif not air_date_raw and len(positional) > 2:
            air_date_raw = positional[2]
        air_date = _parse_air_date(air_date_raw)

        title = kv.get("title")
        if not title and len(positional) > 4:
            title = " ".join(positional[4:])
        title = title or "Untitled"

        task = create_task(
            db,
            TaskCreate(
                title=title,
                type=task_type,
                hashtags=_parse_list(kv.get("hashtags") or kv.get("hashtag")),
                mentions=_parse_list(kv.get("mentions") or kv.get("mention")),
                caption=kv.get("caption"),
                campaign_name=campaign_name,
                campaign_requires_product_url=(kv.get("campaign_requires_product_url", "false").lower() == "true"),
                air_date=air_date,
                status=_parse_status(kv.get("status")) or TaskStatus.idea,
                product_url=kv.get("producturl") or kv.get("product_url"),
                assignee_name=kv.get("assignee"),
                media_urls=req.media_urls,
                created_by_name=sender.name,
                brand=kv.get("brand"),
                platform=kv.get("platform"),
            ),
        )
        payload = task_to_response(task)
        return {
            "message": f"Task {task.id} created with status={task.status}.",
            "task_id": task.id,
            "validate": payload["validate"],
            "dashboard_url": dashboard_link(task.id),
        }

    if command == "/set":
        if len(args) < 2:
            return {
                "message": "Usage: /set <task_id> key=value [key=value]",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        task_id = args[0]
        kv, _ = _parse_kv(args[1:])

        update_payload = TaskUpdate(
            title=kv.get("title"),
            caption=kv.get("caption"),
            hashtags=_parse_list(kv.get("hashtags") or kv.get("hashtag")) if ("hashtags" in kv or "hashtag" in kv) else None,
            mentions=_parse_list(kv.get("mentions") or kv.get("mention")) if ("mentions" in kv or "mention" in kv) else None,
            product_url=kv.get("product_url") or kv.get("producturl"),
            assignee_name=kv.get("assignee"),
            campaign_name=kv.get("campaign"),
            brand=kv.get("brand"),
            platform=kv.get("platform"),
            type=_parse_type(kv.get("type")),
            status=_parse_status(kv.get("status")),
            air_date=_parse_air_date(kv.get("airdate")),
        )

        task = update_task(db, task_id, update_payload, sender.name)

        if req.media_urls:
            task = add_assets(db, task.id, req.media_urls, sender.name)

        payload = task_to_response(task)
        return {
            "message": f"Task {task.id} updated. status={task.status}",
            "task_id": task.id,
            "validate": payload["validate"],
            "dashboard_url": dashboard_link(task.id),
        }

    if command == "/status":
        if len(args) < 2:
            return {
                "message": "Usage: /status <task_id> <idea|design|ready|posted>",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        task_id = args[0]
        status = _parse_status(args[1])
        if not status:
            return {
                "message": "Invalid status.",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        task = update_task(db, task_id, TaskUpdate(status=status), sender.name)
        payload = task_to_response(task)
        return {
            "message": f"Task {task.id} status changed to {task.status}.",
            "task_id": task.id,
            "validate": payload["validate"],
            "dashboard_url": dashboard_link(task.id),
        }

    if command == "/assign":
        if len(args) < 2:
            return {
                "message": "Usage: /assign <task_id> <assignee_name>",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        task_id = args[0]
        assignee_name = " ".join(args[1:])
        task = update_task(db, task_id, TaskUpdate(assignee_name=assignee_name), sender.name)
        payload = task_to_response(task)
        return {
            "message": f"Task {task.id} assigned to {assignee_name}.",
            "task_id": task.id,
            "validate": payload["validate"],
            "dashboard_url": dashboard_link(task.id),
        }

    if command == "/delete":
        if len(args) < 2 or args[1].lower() != "yes":
            return {
                "message": "Confirm delete with: /delete <task_id> yes",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        task_id = args[0]
        try:
            get_task_by_id(db, task_id)
        except ValueError:
            return {
                "message": "Task not found.",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }
        delete_task(db, task_id, sender.name)
        return {
            "message": f"Task {task_id} deleted.",
            "task_id": task_id,
            "validate": None,
            "dashboard_url": None,
        }

    if command == "/attach":
        if not req.media_urls:
            return {
                "message": "No media in payload to attach.",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        if not args:
            return {
                "message": "Usage: /attach <task_id|last>",
                "task_id": None,
                "validate": None,
                "dashboard_url": None,
            }

        target = args[0].lower()
        if target == "last":
            latest = _latest_task_for_user(db, sender.id)
            if not latest:
                return {
                    "message": "No latest task found for this user.",
                    "task_id": None,
                    "validate": None,
                    "dashboard_url": None,
                }
            task = add_assets(db, latest.id, req.media_urls, sender.name)
        else:
            task = add_assets(db, target, req.media_urls, sender.name)

        payload = task_to_response(task)
        hint = _build_media_hint(task)
        message = f"Attached {len(req.media_urls)} media file(s) to task {task.id}."
        if hint:
            message = f"{message} {hint}"
        return {
            "message": message,
            "task_id": task.id,
            "validate": payload["validate"],
            "dashboard_url": dashboard_link(task.id),
        }

    return {
        "message": "Unknown command. Use /new, /set, /status, /assign, /delete, /attach.",
        "task_id": None,
        "validate": None,
        "dashboard_url": None,
    }
