from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal
from app.bot import handle_bot_command
from app.database import Base, engine, get_db
from app.etsy_client import etsy_login, etsy_me, etsy_sellers
from app.jobs import process_due_jobs
from app.schemas import (
    AnalyticsBasic,
    AttachAssetsRequest,
    Base64MediaUploadRequest,
    BotWebhookRequest,
    BotWebhookResponse,
    CollectionCreate,
    CollectionOut,
    CollectionTaskUpdate,
    CollectionUpdate,
    ChecklistUpdateRequest,
    HashtagEntryCreate,
    HashtagEntryOut,
    HashtagEntryUpdate,
    HashtagGroupCreate,
    HashtagGroupOut,
    HashtagGroupUpdate,
    LoginRequest,
    PrincipalOut,
    ReminderJobResult,
    ReminderRunRequest,
    ReminderRunResponse,
    SellerOut,
    TaskCommentCreate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    ValidateResult,
)
from app.services import (
    add_assets,
    add_base64_assets,
    add_tasks_to_collection,
    add_comment,
    analytics_basic,
    calendar_view,
    create_collection,
    create_hashtag,
    create_hashtag_group,
    create_task,
    delete_collection,
    delete_hashtag,
    delete_hashtag_group,
    delete_task,
    get_task_by_id,
    kanban_view,
    list_collections,
    list_hashtag_groups,
    list_hashtags,
    list_tasks,
    remove_task_from_collection,
    replace_checklist,
    suggest_hashtags,
    task_to_response,
    update_collection,
    update_hashtag,
    update_hashtag_group,
    update_task,
    validate_for_task,
)

app = FastAPI(title="Social Content Management API", version="0.1.0")
UI_DIR = Path(__file__).resolve().parent / "ui"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
auth_header = HTTPBearer(auto_error=False)

# Legacy dashboard assets (fallback while Vue bundle is not built).
app.mount("/dashboard-static", StaticFiles(directory=UI_DIR), name="dashboard-static")
# Vue production assets from Vite build.
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets", check_dir=False), name="frontend-assets")
app.mount("/media", StaticFiles(directory=UPLOADS_DIR, check_dir=False), name="media-files")


def _ensure_compat_schema() -> None:
    with engine.begin() as conn:
        task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(social_tasks)").fetchall()}
        if "quick_note" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE social_tasks ADD COLUMN quick_note VARCHAR(256)")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_compat_schema()


def _actor_name(actor_name: str | None, principal: Principal) -> str:
    if actor_name and actor_name.strip():
        return actor_name.strip()
    return principal.username


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="missing_authorization")
    return credentials.credentials


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/tasks/{task_id}", include_in_schema=False)
def dashboard_page(task_id: str | None = None):
    _ = task_id
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return FileResponse(UI_DIR / "dashboard.html")


@app.post("/auth/login")
def auth_login_api(payload: LoginRequest):
    return etsy_login(payload.username, payload.password)


@app.get("/auth/me", response_model=PrincipalOut)
def auth_me_api(
    principal: Principal = Depends(get_current_principal),
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_header),
):
    token = _bearer_token(credentials)
    remote_user = etsy_me(token)
    return PrincipalOut(
        user_id=str(remote_user.get("id") or principal.user_id),
        username=str(remote_user.get("username") or principal.username),
        role=str(remote_user.get("role") or principal.role),
        is_admin=(str(remote_user.get("role") or principal.role).lower() == "admin"),
        is_seller=(str(remote_user.get("role") or principal.role).lower() == "user"),
    )


@app.get("/sellers", response_model=list[SellerOut])
def sellers_api(
    _: Principal = Depends(get_current_principal),
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_header),
):
    token = _bearer_token(credentials)
    rows = etsy_sellers(token)
    normalized: list[SellerOut] = []
    for row in rows:
        normalized.append(
            SellerOut(
                id=str(row.get("id") or ""),
                username=str(row.get("username") or row.get("name") or "").strip(),
                is_active=bool(row.get("is_active", True)),
            )
        )
    return [item for item in normalized if item.id and item.username]


@app.post("/tasks", response_model=TaskOut)
def create_task_api(payload: TaskCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    payload.created_by_name = payload.created_by_name or principal.username
    task = create_task(db, payload)
    return task_to_response(task)


@app.get("/tasks", response_model=list[TaskOut])
def list_tasks_api(
    status: str | None = None,
    assignee_id: str | None = None,
    campaign_id: str | None = None,
    collection_id: str | None = None,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    tasks = list_tasks(
        db,
        status=status,
        assignee_id=assignee_id,
        campaign_id=campaign_id,
        collection_id=collection_id,
        date_from=date_from,
        date_to=date_to,
    )
    return [task_to_response(task) for task in tasks]


@app.get("/tasks/{task_id}", response_model=TaskOut)
def get_task_api(task_id: str, db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    try:
        task = get_task_by_id(db, task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task_to_response(task)


@app.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task_api(
    task_id: str,
    payload: TaskUpdate,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        task = update_task(db, task_id, payload, _actor_name(actor_name, principal))
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task_to_response(task)


@app.delete("/tasks/{task_id}")
def delete_task_api(
    task_id: str,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        delete_task(db, task_id, _actor_name(actor_name, principal))
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return {"deleted": True, "task_id": task_id}


@app.post("/tasks/{task_id}/assets", response_model=TaskOut)
def add_assets_api(
    task_id: str,
    payload: AttachAssetsRequest,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        task = add_assets(db, task_id, payload.media_urls, _actor_name(actor_name, principal))
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task_to_response(task)


@app.post("/tasks/{task_id}/assets/base64", response_model=TaskOut)
def add_base64_assets_api(
    task_id: str,
    payload: Base64MediaUploadRequest,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        task = add_base64_assets(db, task_id, payload.files, _actor_name(actor_name, principal))
    except ValueError as exc:
        if str(exc) == "task_not_found":
            raise HTTPException(status_code=404, detail="task_not_found")
        raise HTTPException(status_code=400, detail=str(exc))
    return task_to_response(task)


@app.post("/tasks/{task_id}/validate", response_model=ValidateResult)
def validate_task_api(task_id: str, db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    try:
        task = get_task_by_id(db, task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    result = validate_for_task(task)
    return ValidateResult(ok=result.ok, missing_fields=result.missing_fields)


@app.post("/tasks/{task_id}/comments")
def add_comment_api(
    task_id: str,
    payload: TaskCommentCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        comment = add_comment(db, task_id, payload.content, payload.user_name or principal.username, payload.parent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "content": comment.content,
        "user_id": comment.user_id,
        "parent_id": comment.parent_id,
        "created_at": comment.created_at,
    }


@app.put("/tasks/{task_id}/checklist", response_model=TaskOut)
def replace_checklist_api(
    task_id: str,
    payload: ChecklistUpdateRequest,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        task = replace_checklist(db, task_id, payload, _actor_name(actor_name, principal))
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task_to_response(task)


@app.post("/bot/webhook/zalo", response_model=BotWebhookResponse)
def bot_webhook_api(payload: BotWebhookRequest, db: Session = Depends(get_db)):
    try:
        result = handle_bot_command(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.post("/reminders/run", response_model=ReminderRunResponse)
def run_reminders_api(
    payload: ReminderRunRequest,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    now = payload.now_utc or datetime.now(timezone.utc)
    results = process_due_jobs(db, now, payload.limit)
    return ReminderRunResponse(
        processed=len(results),
        results=[ReminderJobResult(**item) for item in results],
    )


@app.get("/analytics/basic", response_model=AnalyticsBasic)
def analytics_basic_api(db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    return analytics_basic(db)


@app.get("/dashboard/kanban")
def dashboard_kanban_api(db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    return kanban_view(db)


@app.get("/dashboard/calendar")
def dashboard_calendar_api(
    platform: str | None = None,
    assignee_id: str | None = None,
    campaign_id: str | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    return calendar_view(db, platform=platform, assignee_id=assignee_id, campaign_id=campaign_id)


@app.get("/collections", response_model=list[CollectionOut])
def list_collections_api(db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    return list_collections(db)


@app.post("/collections", response_model=CollectionOut)
def create_collection_api(
    payload: CollectionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return create_collection(db, payload.name, payload.description, payload.color, payload.is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/collections/{collection_id}", response_model=CollectionOut)
def update_collection_api(
    collection_id: str,
    payload: CollectionUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return update_collection(
            db,
            collection_id,
            name=payload.name,
            description=payload.description,
            color=payload.color,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.delete("/collections/{collection_id}")
def delete_collection_api(
    collection_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        delete_collection(db, collection_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="collection_not_found")
    return {"deleted": True, "collection_id": collection_id}


@app.post("/collections/{collection_id}/tasks", response_model=CollectionOut)
def add_collection_tasks_api(
    collection_id: str,
    payload: CollectionTaskUpdate,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    try:
        return add_tasks_to_collection(db, collection_id, payload.task_ids)
    except ValueError:
        raise HTTPException(status_code=404, detail="collection_not_found")


@app.delete("/collections/{collection_id}/tasks/{task_id}")
def remove_collection_task_api(
    collection_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    try:
        remove_task_from_collection(db, collection_id, task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="collection_not_found")
    return {"removed": True, "collection_id": collection_id, "task_id": task_id}


@app.get("/hashtag-groups", response_model=list[HashtagGroupOut])
def list_hashtag_groups_api(db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    return list_hashtag_groups(db)


@app.post("/hashtag-groups", response_model=HashtagGroupOut)
def create_hashtag_groups_api(
    payload: HashtagGroupCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        task_type = payload.task_type.value if payload.task_type else None
        return create_hashtag_group(db, payload.name, payload.scope, payload.campaign_name, task_type, payload.is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/hashtag-groups/{group_id}", response_model=HashtagGroupOut)
def update_hashtag_groups_api(
    group_id: str,
    payload: HashtagGroupUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        task_type = payload.task_type.value if payload.task_type else None
        return update_hashtag_group(
            db,
            group_id,
            name=payload.name,
            scope=payload.scope,
            campaign_name=payload.campaign_name,
            task_type=task_type,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.delete("/hashtag-groups/{group_id}")
def delete_hashtag_groups_api(
    group_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        delete_hashtag_group(db, group_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="hashtag_group_not_found")
    return {"deleted": True, "group_id": group_id}


@app.get("/hashtags", response_model=list[HashtagEntryOut])
def list_hashtags_api(
    group_id: str | None = None,
    q: str | None = None,
    is_active: bool | None = None,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    return list_hashtags(db, group_id=group_id, q=q, is_active=is_active)


@app.post("/hashtags", response_model=HashtagEntryOut)
def create_hashtag_api(
    payload: HashtagEntryCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return create_hashtag(db, payload.group_id, payload.tag, payload.is_active)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.patch("/hashtags/{hashtag_id}", response_model=HashtagEntryOut)
def update_hashtag_api(
    hashtag_id: str,
    payload: HashtagEntryUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return update_hashtag(db, hashtag_id, payload.tag, payload.is_active)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.delete("/hashtags/{hashtag_id}")
def delete_hashtag_api(
    hashtag_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        delete_hashtag(db, hashtag_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="hashtag_not_found")
    return {"deleted": True, "hashtag_id": hashtag_id}


@app.get("/hashtags/suggest", response_model=list[HashtagEntryOut])
def suggest_hashtags_api(
    campaign_name: str | None = None,
    task_type: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    return suggest_hashtags(db, campaign_name=campaign_name, task_type=task_type, limit=limit)
