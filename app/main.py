from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal, issue_local_jwt
from app.bot import handle_bot_command
from app.config import ADMIN_BOOTSTRAP_NAME, ADMIN_BOOTSTRAP_PASSWORD, ADMIN_BOOTSTRAP_USERNAME
from app.database import Base, SessionLocal, base_engine, engine, get_db, resolved_schema
from app.etsy_client import etsy_login, etsy_me, etsy_sellers
from app.jobs import process_due_jobs
from app.schemas import (
    AnalyticsBasic,
    AvatarUploadRequest,
    AttachAssetsRequest,
    Base64MediaUploadRequest,
    BotWebhookRequest,
    BotWebhookResponse,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
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
    ProfilePasswordUpdate,
    ProfileUpdate,
    ReminderJobResult,
    ReminderRunRequest,
    ReminderRunResponse,
    SellerOut,
    TaskCommentCreate,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    UserCreate,
    UserOut,
    UserPasswordUpdate,
    UserUpdate,
    ValidateResult,
)
from app.services import (
    add_assets,
    add_base64_assets,
    add_tasks_to_collection,
    add_comment,
    analytics_basic,
    calendar_view,
    create_campaign,
    create_collection,
    create_user,
    create_hashtag,
    create_hashtag_group,
    create_task,
    delete_user,
    delete_campaign,
    delete_collection,
    delete_asset,
    delete_hashtag,
    delete_hashtag_group,
    delete_task,
    get_task_by_id,
    get_user_by_principal,
    kanban_view,
    list_campaigns,
    list_collections,
    list_hashtag_groups,
    list_hashtags,
    list_users,
    list_tasks,
    remove_task_from_collection,
    replace_checklist,
    suggest_hashtags,
    task_to_response,
    update_my_profile,
    update_campaign,
    update_collection,
    update_hashtag,
    update_hashtag_group,
    update_task,
    update_user,
    set_user_password,
    set_user_avatar,
    authenticate_local_user,
    change_my_password,
    ensure_principal_user,
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
    if engine.dialect.name == "postgresql":
        schema_name = resolved_schema or "public"
        with engine.begin() as conn:
            def _has_column(table_name: str, column_name: str) -> bool:
                row = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = :schema_name
                          AND table_name = :table_name
                          AND column_name = :column_name
                        LIMIT 1
                        """
                    ),
                    {
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "column_name": column_name,
                    },
                ).first()
                return row is not None

            if not _has_column("social_tasks", "quick_note"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."social_tasks" ADD COLUMN quick_note VARCHAR(256)')

            if not _has_column("campaigns", "status"):
                conn.exec_driver_sql(
                    f"ALTER TABLE \"{schema_name}\".\"campaigns\" "
                    "ADD COLUMN status VARCHAR(40) DEFAULT 'planning'"
                )
            if not _has_column("campaigns", "start_date"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN start_date VARCHAR(10)')
            if not _has_column("campaigns", "end_date"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN end_date VARCHAR(10)')
            if not _has_column("campaigns", "description"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN description TEXT')
            if not _has_column("campaigns", "link_url"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN link_url VARCHAR(500)')
            if not _has_column("campaigns", "color"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN color VARCHAR(20)')
            if not _has_column("campaigns", "icon"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN icon VARCHAR(16)')
            if not _has_column("campaigns", "updated_at"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."campaigns" ADD COLUMN updated_at TIMESTAMPTZ')
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"campaigns\" "
                "SET status = 'planning' WHERE status IS NULL OR TRIM(status) = ''"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"campaigns\" "
                "SET color = '#d8d2bc' WHERE color IS NULL OR TRIM(color) = ''"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"campaigns\" "
                "SET icon = '📌' WHERE icon IS NULL OR TRIM(icon) = ''"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"campaigns\" "
                "SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
            )

            if not _has_column("users", "username"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."users" ADD COLUMN username VARCHAR(120)')
            if not _has_column("users", "role"):
                conn.exec_driver_sql(
                    f"ALTER TABLE \"{schema_name}\".\"users\" "
                    "ADD COLUMN role VARCHAR(60) DEFAULT 'content'"
                )
            if not _has_column("users", "avatar_url"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."users" ADD COLUMN avatar_url VARCHAR(600)')
            if not _has_column("users", "password_hash"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."users" ADD COLUMN password_hash VARCHAR(255)')
            if not _has_column("users", "is_active"):
                conn.exec_driver_sql(
                    f"ALTER TABLE \"{schema_name}\".\"users\" "
                    "ADD COLUMN is_active BOOLEAN DEFAULT TRUE"
                )
            if not _has_column("users", "updated_at"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."users" ADD COLUMN updated_at TIMESTAMPTZ')
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"users\" "
                "SET role = COALESCE(NULLIF(TRIM(role), ''), 'content')"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"users\" "
                "SET is_active = COALESCE(is_active, TRUE)"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"users\" "
                "SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
            )
            conn.exec_driver_sql(
                f"UPDATE \"{schema_name}\".\"users\" "
                "SET username = LOWER(REPLACE(TRIM(name), ' ', '.')) "
                "WHERE username IS NULL OR TRIM(username) = ''"
            )
        return

    # Compatibility migration for legacy SQLite files.
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        task_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(social_tasks)").fetchall()}
        if "quick_note" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE social_tasks ADD COLUMN quick_note VARCHAR(256)")

        campaign_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(campaigns)").fetchall()}
        if "status" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN status VARCHAR(40) DEFAULT 'planning'")
        if "start_date" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN start_date VARCHAR(10)")
        if "end_date" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN end_date VARCHAR(10)")
        if "description" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN description TEXT")
        if "link_url" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN link_url VARCHAR(500)")
        if "color" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN color VARCHAR(20)")
        if "icon" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN icon VARCHAR(16)")
        if "updated_at" not in campaign_columns:
            conn.exec_driver_sql("ALTER TABLE campaigns ADD COLUMN updated_at DATETIME")
        conn.exec_driver_sql("UPDATE campaigns SET status = 'planning' WHERE status IS NULL OR TRIM(status) = ''")
        conn.exec_driver_sql("UPDATE campaigns SET color = '#d8d2bc' WHERE color IS NULL OR TRIM(color) = ''")
        conn.exec_driver_sql("UPDATE campaigns SET icon = '📌' WHERE icon IS NULL OR TRIM(icon) = ''")
        conn.exec_driver_sql("UPDATE campaigns SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)")

        user_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()}
        if "username" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN username VARCHAR(120)")
        if "role" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN role VARCHAR(60) DEFAULT 'content'")
        if "avatar_url" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(600)")
        if "password_hash" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
        if "is_active" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1")
        if "updated_at" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN updated_at DATETIME")
        conn.exec_driver_sql("UPDATE users SET role = COALESCE(NULLIF(TRIM(role), ''), 'content')")
        conn.exec_driver_sql("UPDATE users SET is_active = COALESCE(is_active, 1)")
        conn.exec_driver_sql("UPDATE users SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)")
        conn.exec_driver_sql(
            "UPDATE users SET username = LOWER(REPLACE(TRIM(name), ' ', '.')) "
            "WHERE username IS NULL OR TRIM(username) = ''"
        )


def _ensure_bootstrap_admin() -> None:
    if not ADMIN_BOOTSTRAP_USERNAME or not ADMIN_BOOTSTRAP_PASSWORD:
        return
    db = SessionLocal()
    try:
        existing = get_user_by_principal(db, "", ADMIN_BOOTSTRAP_USERNAME)
        if existing:
            update_user(
                db,
                existing.id,
                name=ADMIN_BOOTSTRAP_NAME or existing.name,
                username=ADMIN_BOOTSTRAP_USERNAME,
                role="admin",
                is_active=True,
            )
            set_user_password(db, existing.id, ADMIN_BOOTSTRAP_PASSWORD)
            return
        create_user(
            db,
            name=ADMIN_BOOTSTRAP_NAME or ADMIN_BOOTSTRAP_USERNAME,
            username=ADMIN_BOOTSTRAP_USERNAME,
            role="admin",
            password=ADMIN_BOOTSTRAP_PASSWORD,
            is_active=True,
        )
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    if resolved_schema and base_engine.dialect.name == "postgresql":
        with base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{resolved_schema}"'))
    Base.metadata.create_all(bind=engine)
    _ensure_compat_schema()
    _ensure_bootstrap_admin()


def _actor_name(actor_name: str | None, principal: Principal) -> str:
    if actor_name and actor_name.strip():
        return actor_name.strip()
    return principal.username


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="missing_authorization")
    return credentials.credentials


def _require_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/campaigns", include_in_schema=False)
@app.get("/dashboard/users", include_in_schema=False)
@app.get("/dashboard/tasks/{task_id}", include_in_schema=False)
def dashboard_page(task_id: str | None = None):
    _ = task_id
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return FileResponse(UI_DIR / "dashboard.html")


@app.post("/auth/login")
def auth_login_api(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        return etsy_login(payload.username, payload.password)
    except HTTPException as exc:
        # When Etsy auth is unavailable, fallback to local users.
        if exc.status_code not in {401, 403, 404, 405, 422, 500, 502, 503, 504}:
            raise

    local_user = authenticate_local_user(db, payload.username, payload.password)
    if not local_user:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    token = issue_local_jwt(
        user_id=local_user.id,
        username=local_user.username or local_user.name,
        role=local_user.role,
        name=local_user.name,
        avatar_url=local_user.avatar_url,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": local_user.id,
            "username": local_user.username or local_user.name,
            "name": local_user.name,
            "role": local_user.role,
            "avatar_url": local_user.avatar_url,
        },
    }


@app.get("/auth/me", response_model=PrincipalOut)
def auth_me_api(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_header),
):
    remote_user: dict = {}
    if principal.source != "local":
        token = _bearer_token(credentials)
        try:
            remote_user = etsy_me(token)
        except HTTPException:
            remote_user = {}

    local_profile = ensure_principal_user(
        db,
        principal_user_id=str(remote_user.get("id") or principal.user_id),
        principal_username=str(remote_user.get("username") or principal.username),
        role=str(remote_user.get("role") or principal.role),
        name=str(remote_user.get("name") or principal.name or remote_user.get("username") or principal.username),
        avatar_url=str(remote_user.get("avatar_url") or principal.avatar_url or "").strip() or None,
    )
    normalized_role = str(local_profile.role or remote_user.get("role") or principal.role or "content").lower()
    return PrincipalOut(
        user_id=local_profile.id,
        username=str(local_profile.username or principal.username),
        name=local_profile.name,
        role=normalized_role,
        avatar_url=local_profile.avatar_url,
        is_admin=(normalized_role == "admin"),
        is_seller=(normalized_role in {"user", "seller"}),
    )


@app.get("/sellers", response_model=list[SellerOut])
def sellers_api(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_header),
):
    users = list_users(db, include_inactive=False)
    if users:
        return [
            SellerOut(
                id=user.id,
                username=user.username or user.name,
                name=user.name,
                role=user.role,
                avatar_url=user.avatar_url,
                is_active=user.is_active,
            )
            for user in users
            if user.is_active and (user.username or user.name)
        ]

    if principal.source == "local":
        return []

    token = _bearer_token(credentials)
    rows = etsy_sellers(token)
    normalized: list[SellerOut] = []
    for row in rows:
        normalized.append(
            SellerOut(
                id=str(row.get("id") or ""),
                username=str(row.get("username") or row.get("name") or "").strip(),
                name=str(row.get("name") or row.get("username") or "").strip() or None,
                role=str(row.get("role") or "").strip() or None,
                avatar_url=str(row.get("avatar_url") or "").strip() or None,
                is_active=bool(row.get("is_active", True)),
            )
        )
    return [item for item in normalized if item.id and item.username]


@app.get("/users", response_model=list[UserOut])
def list_users_api(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if include_inactive:
        _require_admin(principal)
    return list_users(db, include_inactive=include_inactive)


@app.post("/users", response_model=UserOut)
def create_user_api(
    payload: UserCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    try:
        return create_user(
            db,
            name=payload.name,
            username=payload.username,
            role=payload.role,
            avatar_url=payload.avatar_url,
            password=payload.password,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/users/{user_id}", response_model=UserOut)
def update_user_api(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    try:
        return update_user(
            db,
            user_id,
            name=payload.name,
            username=payload.username,
            role=payload.role,
            avatar_url=payload.avatar_url,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.put("/users/{user_id}/password", response_model=UserOut)
def set_user_password_api(
    user_id: str,
    payload: UserPasswordUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    try:
        return set_user_password(db, user_id, payload.password)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.put("/users/{user_id}/avatar", response_model=UserOut)
def set_user_avatar_api(
    user_id: str,
    payload: AvatarUploadRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    try:
        return set_user_avatar(db, user_id, payload.file)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.delete("/users/{user_id}")
def delete_user_api(
    user_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    try:
        user = delete_user(db, user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="user_not_found")
    return {"deleted": True, "user_id": user.id}


@app.get("/profile", response_model=UserOut)
def me_profile_api(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    user = ensure_principal_user(
        db,
        principal_user_id=principal.user_id,
        principal_username=principal.username,
        role=principal.role,
        name=principal.name or principal.username,
        avatar_url=principal.avatar_url,
    )
    return user


@app.patch("/profile", response_model=UserOut)
def update_me_profile_api(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    user = get_user_by_principal(db, principal.user_id, principal.username)
    if not user:
        user = ensure_principal_user(
            db,
            principal_user_id=principal.user_id,
            principal_username=principal.username,
            role=principal.role,
            name=principal.name or principal.username,
            avatar_url=principal.avatar_url,
        )
    try:
        return update_my_profile(
            db,
            user_id=user.id,
            name=payload.name,
            username=payload.username,
            avatar_url=payload.avatar_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/profile/avatar", response_model=UserOut)
def set_my_avatar_api(
    payload: AvatarUploadRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    user = get_user_by_principal(db, principal.user_id, principal.username)
    if not user:
        user = ensure_principal_user(
            db,
            principal_user_id=principal.user_id,
            principal_username=principal.username,
            role=principal.role,
            name=principal.name or principal.username,
            avatar_url=principal.avatar_url,
        )
    try:
        return set_user_avatar(db, user.id, payload.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/profile/password", response_model=UserOut)
def change_my_password_api(
    payload: ProfilePasswordUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    user = get_user_by_principal(db, principal.user_id, principal.username)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    try:
        return change_my_password(
            db,
            user_id=user.id,
            current_password=payload.current_password or "",
            new_password=payload.new_password,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=400, detail=detail)


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


@app.delete("/tasks/{task_id}/assets/{asset_id}", response_model=TaskOut)
def delete_asset_api(
    task_id: str,
    asset_id: str,
    actor_name: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    try:
        task = delete_asset(db, task_id, asset_id, _actor_name(actor_name, principal))
    except ValueError as exc:
        if str(exc) in {"task_not_found", "asset_not_found"}:
            raise HTTPException(status_code=404, detail=str(exc))
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


@app.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns_api(db: Session = Depends(get_db), _: Principal = Depends(get_current_principal)):
    return list_campaigns(db)


@app.post("/campaigns", response_model=CampaignOut)
def create_campaign_api(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return create_campaign(
            db,
            payload.name,
            status=payload.status,
            start_date=payload.start_date,
            end_date=payload.end_date,
            description=payload.description,
            link_url=payload.link_url,
            color=payload.color,
            icon=payload.icon,
            requires_product_url=payload.requires_product_url,
            brand=payload.brand,
            platform=payload.platform,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign_api(
    campaign_id: str,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        return update_campaign(
            db,
            campaign_id,
            name=payload.name,
            status=payload.status,
            start_date=payload.start_date,
            end_date=payload.end_date,
            description=payload.description,
            link_url=payload.link_url,
            color=payload.color,
            icon=payload.icon,
            requires_product_url=payload.requires_product_url,
            brand=payload.brand,
            platform=payload.platform,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail.endswith("not_found") else 400, detail=detail)


@app.delete("/campaigns/{campaign_id}")
def delete_campaign_api(
    campaign_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="admin_only")
    try:
        delete_campaign(db, campaign_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="campaign_not_found")
    return {"deleted": True, "campaign_id": campaign_id}


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
