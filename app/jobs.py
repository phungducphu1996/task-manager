from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from app.config import BOT_OWNER_FALLBACK
from app.models import NotificationJob, NotificationLog, SocialTask
from app.notifier import send_package, send_text
from app.validation import LOCAL_TZ, ValidationResult, ensure_localized_air_date, validate_task

JOB_T_MINUS_3 = "t_minus_3_status"
JOB_T_MINUS_2 = "t_minus_2_product_url"
JOB_T_MINUS_1 = "t_minus_1_validate"
JOB_AIRDATE_1900 = "airdate_1900_full_post"

ALL_REMINDER_JOB_TYPES = [
    JOB_T_MINUS_3,
    JOB_T_MINUS_2,
    JOB_T_MINUS_1,
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

    db.commit()
    return results
