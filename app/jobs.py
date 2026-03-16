from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.config import BOT_OWNER_FALLBACK, DAILY_DIGEST_HOUR_LOCAL, DASHBOARD_BASE_URL, SOCIAL_GROUP_CHAT_ID
from app.models import NotificationJob, NotificationLog, SocialTask, SystemSetting
from app.notifier import send_package, send_text
from app.services import PREVIEW_REASON_T_MINUS_1H, send_preview_link_notification
from app.task_notifications import SETTING_SOCIAL_GROUP_CHAT_ID
from app.validation import LOCAL_TZ, ValidationResult, ensure_localized_air_date, validate_task

JOB_T_MINUS_3 = "t_minus_3_status"
JOB_T_MINUS_2 = "t_minus_2_product_url"
JOB_T_MINUS_1 = "t_minus_1_validate"
JOB_T_MINUS_1H_PREVIEW_LINK = "t_minus_1h_preview_link"
JOB_AIRDATE_1900 = "airdate_1900_full_post"
JOB_DAILY_DIGEST_0900 = "daily_digest_0900"
SETTING_DAILY_DIGEST_LAST_SENT_LOCAL_DATE = "daily_digest_last_sent_local_date"

ALL_REMINDER_JOB_TYPES = [
    JOB_T_MINUS_3,
    JOB_T_MINUS_2,
    JOB_T_MINUS_1,
    JOB_T_MINUS_1H_PREVIEW_LINK,
    JOB_AIRDATE_1900,
]


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(timezone.utc)


def build_task_schedule(task: SocialTask) -> dict[str, datetime]:
    if not task.air_date:
        return {}
    local_air = ensure_localized_air_date(task.air_date)
    if not local_air:
        return {}

    final_local = local_air.replace(hour=19, minute=0, second=0, microsecond=0)
    return {
        JOB_T_MINUS_3: _to_utc(local_air - timedelta(days=3)),
        JOB_T_MINUS_2: _to_utc(local_air - timedelta(days=2)),
        JOB_T_MINUS_1: _to_utc(local_air - timedelta(days=1)),
        JOB_T_MINUS_1H_PREVIEW_LINK: _to_utc(local_air - timedelta(hours=1)),
        JOB_AIRDATE_1900: _to_utc(final_local),
    }


def schedule_task_jobs(db: Session, task: SocialTask) -> None:
    db.execute(
        delete(NotificationJob).where(
            NotificationJob.task_id == task.id,
            NotificationJob.status == "pending",
            NotificationJob.job_type.in_(ALL_REMINDER_JOB_TYPES),
        )
    )

    schedule = build_task_schedule(task)
    for job_type, run_at in schedule.items():
        db.add(
            NotificationJob(
                task_id=task.id,
                job_type=job_type,
                run_at=run_at,
                status="pending",
                payload={},
            )
        )


def _format_missing(result: ValidationResult) -> str:
    if result.ok:
        return "none"
    return ", ".join(result.missing_fields)


def _build_full_post_package(task: SocialTask) -> dict:
    hashtags_line = " ".join(task.hashtags or [])
    mentions_line = " ".join(task.mentions or [])
    checklist_summary = [
        {"title": item.title, "is_done": item.is_done}
        for item in sorted(task.checklist_items, key=lambda i: i.position)
    ]
    return {
        "title": task.title,
        "media": [asset.url for asset in task.assets],
        "caption": task.caption or "",
        "hashtags": hashtags_line,
        "mentions": mentions_line,
        "product_url": task.product_url or "",
        "checklist": checklist_summary,
        "task_id": task.id,
    }


def _recipient(task: SocialTask) -> str:
    if task.assignee and task.assignee.name:
        return task.assignee.name
    return BOT_OWNER_FALLBACK


def _resolve_group_chat_id(db: Session) -> tuple[str | None, str]:
    setting = db.get(SystemSetting, SETTING_SOCIAL_GROUP_CHAT_ID)
    db_value = str(setting.value or "").strip() if setting else ""
    if db_value:
        return db_value, "db"
    if SOCIAL_GROUP_CHAT_ID:
        return SOCIAL_GROUP_CHAT_ID, "env"
    return None, "none"


def _upsert_system_setting(db: Session, key: str, value: str) -> None:
    row = db.get(SystemSetting, key)
    if row:
        row.value = value
        return
    db.add(SystemSetting(key=key, value=value))


def _task_link(task_id: str) -> str:
    return f"{DASHBOARD_BASE_URL}/{task_id}"


def _digest_task_line(task: SocialTask) -> str:
    local_air = ensure_localized_air_date(task.air_date)
    local_air_text = local_air.strftime("%H:%M") if local_air else "--:--"
    type_text = str(task.type or "task").upper()
    assignee_text = task.assignee.name if task.assignee and task.assignee.name else "Unassigned"
    return f"- [{local_air_text}] {type_text} · {task.title} · {assignee_text}\n  🔗 {_task_link(task.id)}"


def _send_digest_message(
    db: Session,
    *,
    message: str,
    target: dict,
    recipient_label: str,
    local_date_key: str,
) -> tuple[str, dict]:
    try:
        notify_result = send_text(
            message,
            target=target,
            event_type=JOB_DAILY_DIGEST_0900,
        )
    except Exception as exc:  # pragma: no cover - safety net
        notify_result = {"ok": False, "error": "zalo_send_exception", "detail": str(exc)}

    status = "sent" if notify_result.get("ok") else "failed"
    db.add(
        NotificationLog(
            task_id=None,
            channel="zalo",
            recipient=recipient_label,
            message=message,
            payload={
                "event_type": JOB_DAILY_DIGEST_0900,
                "target": target,
                "local_date": local_date_key,
                "worker_result": notify_result,
            },
            status=status,
        )
    )
    return status, notify_result


def _process_daily_digest(db: Session, now_utc: datetime) -> list[dict]:
    local_now = now_utc.astimezone(LOCAL_TZ)
    local_date_key = local_now.date().isoformat()
    result_job_id = f"digest-{local_date_key}"

    if local_now.hour < DAILY_DIGEST_HOUR_LOCAL:
        return []

    digest_state = db.get(SystemSetting, SETTING_DAILY_DIGEST_LAST_SENT_LOCAL_DATE)
    if digest_state and str(digest_state.value or "").strip() == local_date_key:
        return []

    tasks = (
        db.execute(
            select(SocialTask)
            .where(SocialTask.air_date.is_not(None))
            .options(joinedload(SocialTask.assignee))
            .order_by(SocialTask.air_date.asc())
        )
        .scalars()
        .unique()
        .all()
    )

    today_tasks: list[SocialTask] = []
    overdue_tasks: list[SocialTask] = []
    for task in tasks:
        local_air = ensure_localized_air_date(task.air_date)
        if not local_air:
            continue
        if local_air.date() == local_now.date():
            today_tasks.append(task)
        if local_air < local_now and str(task.status or "").lower() != "posted":
            overdue_tasks.append(task)

    today_lines = [_digest_task_line(task) for task in today_tasks[:20]]
    overdue_lines = [_digest_task_line(task) for task in overdue_tasks[:20]]
    dashboard_link = DASHBOARD_BASE_URL.rsplit("/", 1)[0] if "/" in DASHBOARD_BASE_URL else DASHBOARD_BASE_URL
    group_message_parts = [
        f"🗓️ Daily Digest {local_now.strftime('%d/%m/%Y')} (09:00 +07)",
        f"Hôm nay: {len(today_tasks)} task",
        f"Quá hạn: {len(overdue_tasks)} task",
    ]
    if today_lines:
        group_message_parts.extend(["", "Task hôm nay:", *today_lines])
    if overdue_lines:
        group_message_parts.extend(["", "Task quá hạn:", *overdue_lines])
    group_message_parts.extend(["", f"📍 Dashboard: {dashboard_link}"])
    group_message = "\n".join(group_message_parts)

    group_chat_id, group_source = _resolve_group_chat_id(db)
    sent_count = 0
    failed_count = 0

    if group_chat_id:
        status, _notify_result = _send_digest_message(
            db,
            message=group_message,
            target={"group_chat_id": group_chat_id},
            recipient_label=f"group:{group_chat_id}",
            local_date_key=local_date_key,
        )
        if status == "sent":
            sent_count += 1
        else:
            failed_count += 1

    assignee_digest: dict[str, dict] = {}
    for task in today_tasks:
        assignee = task.assignee
        if not assignee or not assignee.zalo_user_id:
            continue
        key = assignee.id
        if key not in assignee_digest:
            assignee_digest[key] = {"user": assignee, "today": [], "overdue": []}
        assignee_digest[key]["today"].append(task)
    for task in overdue_tasks:
        assignee = task.assignee
        if not assignee or not assignee.zalo_user_id:
            continue
        key = assignee.id
        if key not in assignee_digest:
            assignee_digest[key] = {"user": assignee, "today": [], "overdue": []}
        assignee_digest[key]["overdue"].append(task)

    for payload in assignee_digest.values():
        assignee = payload["user"]
        assignee_name = assignee.name or assignee.username or "Bạn"
        dm_parts = [
            f"👋 Digest của {assignee_name} · {local_now.strftime('%d/%m/%Y')}",
            f"Task hôm nay: {len(payload['today'])}",
            f"Task quá hạn: {len(payload['overdue'])}",
        ]
        if payload["today"]:
            dm_parts.extend(["", "Cần làm hôm nay:", *[_digest_task_line(task) for task in payload["today"][:20]]])
        if payload["overdue"]:
            dm_parts.extend(["", "Đang quá hạn:", *[_digest_task_line(task) for task in payload["overdue"][:20]]])
        dm_message = "\n".join(dm_parts)
        status, _notify_result = _send_digest_message(
            db,
            message=dm_message,
            target={"user_zalo_id": assignee.zalo_user_id},
            recipient_label=f"user:{assignee.zalo_user_id}",
            local_date_key=local_date_key,
        )
        if status == "sent":
            sent_count += 1
        else:
            failed_count += 1

    if sent_count == 0 and failed_count == 0:
        db.add(
            NotificationLog(
                task_id=None,
                channel="zalo",
                recipient=None,
                message=group_message,
                payload={
                    "event_type": JOB_DAILY_DIGEST_0900,
                    "local_date": local_date_key,
                    "settings_source": group_source,
                    "error": "missing_routing_target",
                },
                status="failed",
            )
        )
        failed_count += 1

    _upsert_system_setting(db, SETTING_DAILY_DIGEST_LAST_SENT_LOCAL_DATE, local_date_key)
    status_text = "sent" if failed_count == 0 else ("partial" if sent_count > 0 else "failed")
    return [
        {
            "job_id": result_job_id,
            "task_id": "daily-digest",
            "job_type": JOB_DAILY_DIGEST_0900,
            "status": status_text,
            "message": f"Daily digest sent={sent_count} failed={failed_count}",
        }
    ]


def process_due_jobs(db: Session, now_utc: datetime, limit: int = 200) -> list[dict]:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    jobs = (
        db.execute(
            select(NotificationJob)
            .where(NotificationJob.status == "pending", NotificationJob.run_at <= now_utc)
            .order_by(NotificationJob.run_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    results: list[dict] = []

    for job in jobs:
        task = (
            db.execute(
                select(SocialTask)
                .where(SocialTask.id == job.task_id)
                .options(
                    joinedload(SocialTask.assets),
                    joinedload(SocialTask.checklist_items),
                    joinedload(SocialTask.campaign),
                    joinedload(SocialTask.assignee),
                )
            )
            .scalars()
            .first()
        )

        if not task:
            job.status = "failed"
            results.append(
                {
                    "job_id": job.id,
                    "task_id": job.task_id,
                    "job_type": job.job_type,
                    "status": "failed",
                    "message": "task not found",
                }
            )
            continue

        campaign_requires_url = bool(task.campaign and task.campaign.requires_product_url)
        validation = validate_task(task, campaign_requires_url)
        recipient = _recipient(task)
        payload: dict = {}

        if job.job_type == JOB_T_MINUS_3:
            message = f"[T-3] Update status/progress for task {task.id} - {task.title}."
            notify_result = send_text(message)
        elif job.job_type == JOB_T_MINUS_2:
            message = f"[T-2] Update product_url for task {task.id} if campaign requires sales URL."
            notify_result = send_text(message)
        elif job.job_type == JOB_T_MINUS_1:
            message = (
                f"[T-1] Prepare posting. Missing fields for task {task.id}: {_format_missing(validation)}"
            )
            payload["missing_fields"] = validation.missing_fields
            notify_result = send_text(message)
        elif job.job_type == JOB_T_MINUS_1H_PREVIEW_LINK:
            preview_result = send_preview_link_notification(
                db,
                task=task,
                reason=PREVIEW_REASON_T_MINUS_1H,
                context={"trigger": "reminder_job", "job_id": job.id},
            )
            payload["preview_result"] = preview_result
            notify_result = {"ok": bool(preview_result.get("ok"))}
            if preview_result.get("skipped") == "already_sent":
                message = f"[T-1H] Preview link already sent for task {task.title}."
            elif preview_result.get("ok"):
                message = f"[T-1H] Preview link sent for task {task.title}."
            else:
                message = f"[T-1H] Preview link failed for task {task.title}."
        elif job.job_type == JOB_AIRDATE_1900:
            if validation.ok:
                package = _build_full_post_package(task)
                message = f"[AIRDATE 19:00] Full post package for task {task.id}: ready to post."
                payload["full_post_package"] = package
                notify_result = send_package(package)
            else:
                message = (
                    f"[AIRDATE 19:00] Task {task.id} is missing: {_format_missing(validation)}"
                )
                payload["missing_fields"] = validation.missing_fields
                notify_result = send_text(message)
        else:
            message = f"Unknown job type {job.job_type}"
            notify_result = {"ok": False, "error": "unknown_job_type"}

        payload["notify_result"] = notify_result
        sent_ok = bool(notify_result.get("ok"))
        log_status = "sent" if sent_ok else "failed"
        job.status = log_status

        db.add(
            NotificationLog(
                task_id=task.id,
                job_id=job.id,
                channel="zalo",
                recipient=recipient,
                message=message,
                payload=payload,
                status=log_status,
            )
        )

        results.append(
            {
                "job_id": job.id,
                "task_id": task.id,
                "job_type": job.job_type,
                "status": log_status,
                "message": message,
            }
        )

    results.extend(_process_daily_digest(db, now_utc))
    db.commit()
    return results
