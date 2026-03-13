from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import DASHBOARD_BASE_URL, SOCIAL_GROUP_CHAT_ID
from app.models import NotificationLog, SocialTask, SystemSetting, User
from app.notifier import send_text

SETTING_SOCIAL_GROUP_CHAT_ID = "social_group_chat_id"
KEY_FIELD_NOTIFICATION_SCOPE = {"caption", "hashtags", "mentions"}

STATUS_LABELS = {
    "idea": "Idea",
    "design": "Design",
    "ready": "Ready",
    "posted": "Posted",
}

TYPE_LABELS = {
    "story": "Story",
    "reel": "Reel",
    "post": "Post",
}

FIELD_LABELS = {
    "caption": "caption",
    "hashtags": "hashtags",
    "mentions": "mentions",
}


def _task_url(task_id: str) -> str:
    return f"{DASHBOARD_BASE_URL}/{task_id}"


def _status_label(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return STATUS_LABELS.get(key, key or "unknown")


def _type_label(value: str | None) -> str:
    key = str(value or "").strip().lower()
    return TYPE_LABELS.get(key, key or "Task")


def _actor_name(actor: User | None) -> str:
    if actor and actor.name:
        return actor.name
    if actor and actor.username:
        return actor.username
    return "Hệ thống"


def _resolve_group_chat_id(db: Session) -> tuple[str | None, str]:
    setting = db.get(SystemSetting, SETTING_SOCIAL_GROUP_CHAT_ID)
    if setting and str(setting.value or "").strip():
        return str(setting.value).strip(), "db"
    if SOCIAL_GROUP_CHAT_ID:
        return SOCIAL_GROUP_CHAT_ID, "env"
    return None, "none"


def _assignee_mention(task: SocialTask) -> tuple[list[dict[str, str]], str]:
    assignee_name = task.assignee.name if task.assignee and task.assignee.name else "assignee"
    if task.assignee and task.assignee.zalo_user_id:
        return [{"zalo_user_id": task.assignee.zalo_user_id, "text": assignee_name}], f"@{assignee_name}"
    return [{"text": assignee_name}], f"@{assignee_name}"


def _text_preview(raw: str | None, max_len: int = 80) -> str:
    text = str(raw or "").strip().replace("\n", " ")
    if not text:
        return "(trống)"
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1]}…"


def _build_message(
    event_type: str,
    task: SocialTask,
    actor: User | None,
    task_url: str,
    context: dict[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    actor_name = _actor_name(actor)
    task_type = _type_label(task.type)
    task_line = f"{task.title} ({task_type})"
    mentions: list[dict[str, str]] = []

    if event_type == "task_created":
        body = f"🆕 {actor_name} vừa tạo task: {task_line}"
    elif event_type == "task_status_changed":
        old_status = _status_label(context.get("old_status"))
        new_status = _status_label(context.get("new_status") or task.status)
        body = f"🔄 {actor_name} đổi trạng thái task {task_line}: {old_status} → {new_status}"
    elif event_type == "task_assigned":
        mentions, tag_text = _assignee_mention(task)
        body = f"👤 {actor_name} đã assign task {task_line} cho {tag_text}"
    elif event_type == "task_content_updated":
        changed_fields = context.get("changed_fields") or []
        labels = [FIELD_LABELS.get(str(field), str(field)) for field in changed_fields]
        changed_text = ", ".join(labels) if labels else "nội dung"
        body = f"✏️ {actor_name} cập nhật {changed_text} của task {task_line}"
    elif event_type == "task_media_uploaded":
        media_count = int(context.get("media_count") or 0)
        body = f"🖼️ {actor_name} đã upload {media_count} media vào task {task_line}"
    elif event_type == "task_comment_added":
        preview = _text_preview(context.get("comment_text"))
        body = f"💬 {actor_name} bình luận mới ở task {task_line}: {preview}"
    else:
        body = f"📣 {actor_name} cập nhật task {task_line}"

    return f"{body}\n🔗 {task_url}", mentions


def _recipient_label(target: dict[str, Any]) -> str:
    if target.get("group_chat_id"):
        return f"group:{target['group_chat_id']}"
    if target.get("user_zalo_id"):
        return f"user:{target['user_zalo_id']}"
    return "unknown"


def emit_task_notification(
    db: Session,
    event_type: str,
    task: SocialTask,
    actor: User | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    context_data = context or {}
    task_url = _task_url(task.id)
    group_chat_id, group_source = _resolve_group_chat_id(db)
    message, mentions = _build_message(event_type, task, actor, task_url, context_data)

    targets: list[dict[str, Any]] = []
    if group_chat_id:
        group_target: dict[str, Any] = {"group_chat_id": group_chat_id}
        if mentions:
            group_target["mentions"] = mentions
        targets.append(group_target)

    assignee_zalo_id = str(task.assignee.zalo_user_id).strip() if task.assignee and task.assignee.zalo_user_id else ""
    if event_type == "task_assigned" and assignee_zalo_id:
        targets.append({"user_zalo_id": assignee_zalo_id, "mentions": mentions})
    elif not group_chat_id and assignee_zalo_id:
        targets.append({"user_zalo_id": assignee_zalo_id})

    if not targets:
        db.add(
            NotificationLog(
                task_id=task.id,
                channel="zalo",
                recipient=None,
                message=message,
                payload={
                    "event_type": event_type,
                    "task_url": task_url,
                    "target": None,
                    "settings_source": group_source,
                    "error": "missing_routing_target",
                },
                status="failed",
            )
        )
        db.commit()
        return

    for target in targets:
        target_payload = {
            "group_chat_id": target.get("group_chat_id"),
            "user_zalo_id": target.get("user_zalo_id"),
            "mentions": target.get("mentions") or [],
            "task_url": task_url,
            "event_type": event_type,
        }
        try:
            worker_result = send_text(
                message,
                target=target_payload,
                task_url=task_url,
                event_type=event_type,
            )
        except Exception as exc:  # pragma: no cover - safety net
            worker_result = {"ok": False, "error": "zalo_send_exception", "detail": str(exc)}

        status = "sent" if worker_result.get("ok") else "failed"
        db.add(
            NotificationLog(
                task_id=task.id,
                channel="zalo",
                recipient=_recipient_label(target_payload),
                message=message,
                payload={
                    "event_type": event_type,
                    "task_url": task_url,
                    "target": target_payload,
                    "settings_source": group_source,
                    "context": context_data,
                    "worker_result": worker_result,
                },
                status=status,
            )
        )

    db.commit()
