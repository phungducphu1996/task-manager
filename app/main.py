from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
    ZaloSettingsOut,
    ZaloSettingsUpdate,
    TaskCommentCreate,
    TaskCreate,
    TaskOut,
    TaskPreviewLinkOut,
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
    get_task_preview_link,
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
    regenerate_task_preview_link,
    resolve_public_preview_task,
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
    send_zalo_test_notification,
    authenticate_local_user,
    change_my_password,
    ensure_principal_user,
    get_zalo_settings,
    update_zalo_settings,
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
            if not _has_column("social_tasks", "note_color"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."social_tasks" ADD COLUMN note_color VARCHAR(20)')

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
            if not _has_column("users", "zalo_user_id"):
                conn.exec_driver_sql(f'ALTER TABLE "{schema_name}"."users" ADD COLUMN zalo_user_id VARCHAR(120)')
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
        if "note_color" not in task_columns:
            conn.exec_driver_sql("ALTER TABLE social_tasks ADD COLUMN note_color VARCHAR(20)")

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
        if "zalo_user_id" not in user_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN zalo_user_id VARCHAR(120)")
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


def _preview_type_label(task_type: str | None) -> str:
    mapping = {"story": "Story", "reel": "Reel", "post": "Post"}
    key = str(task_type or "").strip().lower()
    return mapping.get(key, key or "Task")


def _format_preview_air_date(value: datetime | None) -> str:
    if not value:
        return "No air date"
    return value.strftime("%d/%m/%Y %H:%M")


def _render_public_preview_error_page(title: str, message: str) -> str:
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{safe_title}</title>
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        font-family: "Wix Madefor Display", "Segoe UI", sans-serif;
        background: #111;
        color: #f8f1d9;
        display: grid;
        place-items: center;
      }}
      .card {{
        width: min(640px, calc(100vw - 24px));
        border: 2px solid #f8f1d9;
        border-radius: 20px;
        background: #1d1d1d;
        padding: 22px;
      }}
      h1 {{ margin: 0 0 8px; font-size: 1.8rem; }}
      p {{ margin: 0; color: #d7cfb3; }}
    </style>
  </head>
  <body>
    <article class="card">
      <h1>{safe_title}</h1>
      <p>{safe_message}</p>
    </article>
  </body>
</html>"""


def _render_public_preview_page(payload: dict) -> str:
    raw_title = str(payload.get("title") or "Untitled task").strip() or "Untitled task"
    type_key = str(payload.get("type") or "").strip().lower()
    task_type = _preview_type_label(type_key)
    status_text = str(payload.get("status") or "idea").strip().upper()
    air_date_text = _format_preview_air_date(payload.get("air_date"))
    campaign_name = str(payload.get("campaign_name") or "No campaign").strip() or "No campaign"
    assignee_name = str(payload.get("assignee_name") or "Unassigned").strip() or "Unassigned"
    caption_text = str(payload.get("caption") or "").strip()
    hashtag_text = " ".join(payload.get("hashtags") or []).strip()
    mention_text = " ".join(payload.get("mentions") or []).strip()
    quick_note_text = str(payload.get("quick_note") or "").strip()
    expires_at = payload.get("token_expires_at")
    expires_text = _format_preview_air_date(expires_at) if isinstance(expires_at, datetime) else "Unknown"

    assets_data = []
    for asset in payload.get("assets") or []:
        url = str(asset.get("url") or "").strip()
        if not url:
            continue
        kind = str(asset.get("kind") or "image").strip().lower()
        assets_data.append({"kind": "video" if kind == "video" else "image", "url": url})

    preview_data = {
        "title": raw_title,
        "type": type_key or "post",
        "type_label": task_type,
        "status": status_text,
        "air_date": air_date_text,
        "campaign_name": campaign_name,
        "assignee_name": assignee_name,
        "caption": caption_text,
        "hashtags": hashtag_text,
        "mentions": mention_text,
        "quick_note": quick_note_text,
        "expires_at": expires_text,
        "assets": assets_data,
    }
    payload_json = json.dumps(preview_data, ensure_ascii=False).replace("</", "<\\/")
    page_title = html.escape(raw_title)

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Public Preview - {page_title}</title>
    <style>
      :root {{
        color-scheme: light;
      }}
      body {{
        margin: 0;
        min-height: 100vh;
        font-family: "Wix Madefor Display", "Segoe UI", sans-serif;
        background: #f0f1f4;
        color: #111;
        padding: 16px;
      }}
      .wrap {{
        width: min(980px, 100%);
        margin: 0 auto;
        border: 2px solid #222;
        border-radius: 24px;
        background: #fffef8;
        overflow: hidden;
      }}
      .head {{
        padding: 16px 18px;
        border-bottom: 2px solid #222;
        background: #fdf3df;
      }}
      .head h1 {{
        margin: 0;
        font-size: 1.65rem;
        line-height: 1.1;
      }}
      .meta {{
        margin-top: 6px;
        color: #565142;
        font-size: 0.92rem;
      }}
      .chip-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 8px;
      }}
      .chip {{
        display: inline-flex;
        padding: 3px 9px;
        border: 1.6px solid #222;
        border-radius: 999px;        
        font-size: 0.82rem;
        font-weight: 700;
      }}
      .body {{
        padding: 14px 16px 20px;
      }}
      .toolbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .device-switch {{
        display: inline-flex;
        gap: 8px;
      }}
      .switch-btn,
      .ghost-btn {{
        border: 1.8px solid #222;
        border-radius: 999px;
        background: #fff;
        padding: 6px 12px;
        font: inherit;
        font-size: 0.86rem;
        font-weight: 700;
        cursor: pointer;
      }}
      .switch-btn.active {{
        background: #ffe9d4;
      }}
      .ghost-btn[disabled] {{
        opacity: 0.55;
        cursor: default;
      }}
      .ig-shell {{
        margin-top: 10px;
        border: 2px solid #222;
        border-radius: 16px;
        background: #fff;
        padding: 12px;
      }}
      .ig-shell.device-mobile {{
        max-width: 420px;
        margin-left: auto;
        margin-right: auto;
      }}
      .ig-shell.device-desktop {{
        max-width: 760px;
        margin-left: auto;
        margin-right: auto;
      }}
      .ig-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }}
      .ig-user {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }}
      .ig-platform {{
        border-radius: 999px;
        background: #d94e78;
        color: #fff;
        font-size: 0.76rem;
        font-weight: 700;
        padding: 3px 9px;
      }}
      .ig-type {{
        border: 1.8px solid #222;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 0.8rem;
        font-weight: 700;
        background: #fff7df;
      }}
      .ig-media-wrap {{
        margin-top: 10px;
        border: 2px solid #222;
        border-radius: 14px;
        overflow: hidden;
        background: #f2f0e2;
        width: 100%;
        aspect-ratio: 1 / 1;
      }}
      .ig-media-wrap.story {{
        aspect-ratio: 9 / 16;
      }}
      .ig-media {{
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
        background: #f2f0e2;
      }}
      .no-media {{
        width: 100%;
        height: 100%;
        padding: 14px;
        display: grid;
        align-content: center;
        white-space: pre-wrap;
        word-break: break-word;
        color: #4d493f;
      }}
      .carousel {{
        margin-top: 10px;
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }}
      .carousel-label {{
        min-width: 56px;
        text-align: center;
        color: #5f5a4d;
        font-size: 0.84rem;
      }}
      .fields {{
        margin-top: 12px;
        display: grid;
        gap: 10px;
      }}
      .field {{
        border: 1.8px solid #222;
        border-radius: 12px;
        background: #fff;
        padding: 10px 12px;
      }}
      .field-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }}
      .field-label {{
        font-size: 0.78rem;
        color: #6a6456;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 700;
      }}
      .copy-btn {{
        border: 1.6px solid #222;
        border-radius: 999px;
        background: #fff;
        padding: 2px 8px;
        font: inherit;
        font-size: 0.75rem;
        cursor: pointer;
      }}
      .field-value {{
        margin-top: 6px;
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
      }}
      .field-value.empty {{
        color: #666053;
        font-style: italic;
      }}
      .foot {{
        margin-top: 14px;
        font-size: 0.82rem;
        color: #686251;
      }}
      @media (max-width: 640px) {{
        .head h1 {{ font-size: 1.35rem; }}
        .body {{ padding: 12px; }}
      }}
    </style>
  </head>
  <body>
    <article class="wrap">
      <header class="head">
        <h1 id="taskTitle">{page_title}</h1>
        <div class="meta" id="metaLine"></div>
        <div class="chip-row">
          <span class="chip" id="campaignChip"></span>
          <span class="chip" id="assigneeChip"></span>
        </div>
      </header>
      <section class="body">
        <div class="toolbar">
          <div class="device-switch">
            <button class="switch-btn active" id="desktopBtn" type="button">Desktop</button>
            <button class="switch-btn" id="mobileBtn" type="button">Mobile</button>
          </div>
          <button class="ghost-btn" id="copyContentBtn" type="button">Copy Content</button>
        </div>
        <div class="ig-shell device-desktop" id="igShell">
          <header class="ig-head">
            <div class="ig-user">
              <span class="ig-platform">IG</span>
              <strong id="igUser"></strong>
            </div>
            <span class="ig-type" id="igType"></span>
          </header>
          <div class="ig-media-wrap" id="mediaWrap"></div>
          <div class="carousel" id="carouselRow">
            <button class="ghost-btn" id="prevBtn" type="button">Prev</button>
            <span class="carousel-label" id="carouselLabel"></span>
            <button class="ghost-btn" id="nextBtn" type="button">Next</button>
          </div>
          <div class="fields" id="fieldRows"></div>
        </div>
        <p class="foot">This is a read-only public preview link. Expires at {html.escape(expires_text)} (+07).</p>
      </section>
    </article>
    <script id="previewPayload" type="application/json">{payload_json}</script>
    <script>
      const payload = JSON.parse(document.getElementById("previewPayload").textContent || "{{}}");
      const state = {{
        device: "desktop",
        index: 0,
      }};
      const desktopBtn = document.getElementById("desktopBtn");
      const mobileBtn = document.getElementById("mobileBtn");
      const igShell = document.getElementById("igShell");
      const mediaWrap = document.getElementById("mediaWrap");
      const carouselRow = document.getElementById("carouselRow");
      const prevBtn = document.getElementById("prevBtn");
      const nextBtn = document.getElementById("nextBtn");
      const carouselLabel = document.getElementById("carouselLabel");
      const fieldRows = document.getElementById("fieldRows");
      const igUser = document.getElementById("igUser");
      const igType = document.getElementById("igType");
      const title = document.getElementById("taskTitle");
      const metaLine = document.getElementById("metaLine");
      const campaignChip = document.getElementById("campaignChip");
      const assigneeChip = document.getElementById("assigneeChip");
      const copyContentBtn = document.getElementById("copyContentBtn");
      const assets = Array.isArray(payload.assets) ? payload.assets : [];
      const typeValue = String(payload.type || "post").toLowerCase();

      function setDevice(device) {{
        state.device = device;
        desktopBtn.classList.toggle("active", device === "desktop");
        mobileBtn.classList.toggle("active", device === "mobile");
        igShell.classList.toggle("device-desktop", device === "desktop");
        igShell.classList.toggle("device-mobile", device === "mobile");
      }}

      function currentAsset() {{
        if (assets.length === 0) return null;
        const safeIndex = Math.min(Math.max(state.index, 0), assets.length - 1);
        return assets[safeIndex];
      }}

      function copyText(value) {{
        const text = String(value || "").trim();
        if (!text) return;
        navigator.clipboard?.writeText(text).catch(() => {{}});
      }}

      function renderMedia() {{
        const asset = currentAsset();
        mediaWrap.innerHTML = "";
        mediaWrap.classList.toggle("story", typeValue === "story");
        if (!asset) {{
          const noMedia = document.createElement("div");
          noMedia.className = "no-media";
          noMedia.textContent = payload.quick_note || "No media yet";
          mediaWrap.appendChild(noMedia);
        }} else if (String(asset.kind || "").toLowerCase() === "video") {{
          const video = document.createElement("video");
          video.className = "ig-media";
          video.src = asset.url;
          video.controls = true;
          video.playsInline = true;
          mediaWrap.appendChild(video);
        }} else {{
          const img = document.createElement("img");
          img.className = "ig-media";
          img.src = asset.url;
          img.alt = "";
          mediaWrap.appendChild(img);
        }}
        if (assets.length > 1) {{
          carouselRow.style.display = "inline-flex";
          carouselLabel.textContent = `${{Math.min(state.index + 1, assets.length)}}/${{assets.length}}`;
        }} else {{
          carouselRow.style.display = "none";
        }}
      }}

      function renderFields() {{
        const rows = [
          {{ label: "Caption", value: payload.caption || "", empty: "No caption" }},
          {{ label: "Hashtags", value: payload.hashtags || "", empty: "No hashtags" }},
          {{ label: "Mentions", value: payload.mentions || "", empty: "No mentions" }},
          {{ label: "Quick note", value: payload.quick_note || "", empty: "No quick note" }},
        ];
        fieldRows.innerHTML = "";
        rows.forEach((row) => {{
          const article = document.createElement("article");
          article.className = "field";
          const header = document.createElement("div");
          header.className = "field-head";
          const label = document.createElement("span");
          label.className = "field-label";
          label.textContent = row.label;
          const copy = document.createElement("button");
          copy.className = "copy-btn";
          copy.type = "button";
          copy.textContent = "⧉ Copy";
          copy.disabled = !String(row.value || "").trim();
          copy.addEventListener("click", () => copyText(row.value));
          header.appendChild(label);
          header.appendChild(copy);
          const value = document.createElement("p");
          value.className = "field-value";
          if (!String(row.value || "").trim()) {{
            value.classList.add("empty");
            value.textContent = row.empty;
          }} else {{
            value.textContent = row.value;
          }}
          article.appendChild(header);
          article.appendChild(value);
          fieldRows.appendChild(article);
        }});
      }}

      function render() {{
        title.textContent = payload.title || "Untitled task";
        metaLine.textContent = `${{payload.type_label || "Task"}} · ${{payload.air_date || "No air date"}} · ${{payload.status || "IDEA"}}`;
        campaignChip.textContent = `Campaign: ${{payload.campaign_name || "No campaign"}}`;
        assigneeChip.textContent = `Assignee: ${{payload.assignee_name || "Unassigned"}}`;
        igUser.textContent = payload.assignee_name || "Content Team";
        igType.textContent = String(payload.type || "post").toUpperCase();
        renderMedia();
        renderFields();
      }}

      desktopBtn.addEventListener("click", () => setDevice("desktop"));
      mobileBtn.addEventListener("click", () => setDevice("mobile"));
      prevBtn.addEventListener("click", () => {{
        if (!assets.length) return;
        state.index = (state.index - 1 + assets.length) % assets.length;
        renderMedia();
      }});
      nextBtn.addEventListener("click", () => {{
        if (!assets.length) return;
        state.index = (state.index + 1) % assets.length;
        renderMedia();
      }});
      copyContentBtn.addEventListener("click", () => {{
        const packageText = [payload.caption, payload.hashtags, payload.mentions].filter(Boolean).join("\\n").trim();
        copyText(packageText);
      }});

      setDevice("desktop");
      render();
    </script>
  </body>
</html>"""


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/campaigns", include_in_schema=False)
@app.get("/dashboard/users", include_in_schema=False)
@app.get("/dashboard/task/{task_id}", include_in_schema=False)
@app.get("/dashboard/tasks/{task_id}", include_in_schema=False)
def dashboard_page(task_id: str | None = None):
    _ = task_id
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    return FileResponse(UI_DIR / "dashboard.html")


@app.get("/preview/{token}", include_in_schema=False, response_class=HTMLResponse)
def public_preview_page(token: str, db: Session = Depends(get_db)):
    payload, error = resolve_public_preview_task(db, token)
    if error:
        if error == "expired_token":
            return HTMLResponse(
                _render_public_preview_error_page(
                    "Preview link expired",
                    "Liên kết preview đã hết hạn. Vui lòng yêu cầu link mới từ team Social.",
                ),
                status_code=410,
            )
        if error == "revoked_token":
            return HTMLResponse(
                _render_public_preview_error_page(
                    "Preview link revoked",
                    "Liên kết preview đã bị thu hồi. Vui lòng yêu cầu link mới từ team Social.",
                ),
                status_code=410,
            )
        if error == "task_not_found":
            return HTMLResponse(
                _render_public_preview_error_page(
                    "Task not found",
                    "Task tương ứng không còn tồn tại.",
                ),
                status_code=404,
            )
        return HTMLResponse(
            _render_public_preview_error_page(
                "Invalid preview link",
                "Liên kết preview không hợp lệ hoặc đã bị thay thế.",
            ),
            status_code=404,
        )
    return HTMLResponse(_render_public_preview_page(payload), status_code=200)


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
            "zalo_user_id": local_user.zalo_user_id,
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
            zalo_user_id=payload.zalo_user_id,
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
            zalo_user_id=payload.zalo_user_id,
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
            zalo_user_id=payload.zalo_user_id,
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


@app.get("/settings/zalo", response_model=ZaloSettingsOut)
def get_zalo_settings_api(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    return get_zalo_settings(db)


@app.patch("/settings/zalo", response_model=ZaloSettingsOut)
def update_zalo_settings_api(
    payload: ZaloSettingsUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    return update_zalo_settings(
        db,
        social_group_chat_id=payload.social_group_chat_id,
        actor_name=principal.username,
    )


@app.post("/settings/zalo/test")
def test_zalo_settings_api(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _require_admin(principal)
    result = send_zalo_test_notification(
        db,
        actor_name=principal.username,
        principal_user_id=principal.user_id,
    )
    if not result.get("ok") and int(result.get("sent", 0) or 0) == 0:
        raise HTTPException(status_code=400, detail=str(result.get("error") or "zalo_test_failed"))
    return result


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


@app.get("/tasks/{task_id}/preview-link", response_model=TaskPreviewLinkOut)
def get_task_preview_link_api(
    task_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_current_principal),
):
    try:
        return TaskPreviewLinkOut(**get_task_preview_link(db, task_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")


@app.post("/tasks/{task_id}/preview-link", response_model=TaskPreviewLinkOut)
def regenerate_task_preview_link_api(
    task_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    actor = get_user_by_principal(db, principal.user_id, principal.username)
    actor_id = actor.id if actor else None
    try:
        payload = regenerate_task_preview_link(db, task_id, actor_id=actor_id)
        return TaskPreviewLinkOut(**payload)
    except ValueError:
        raise HTTPException(status_code=404, detail="task_not_found")


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
