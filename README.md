# Social Content Management MVP (FastAPI)

MVP backend for a single-source-of-truth social content system:
- Core Task Service (CRUD, media attach, validate, audit)
- Zalo chatbot webhook commands
- Reminder engine with milestone rules
- Basic analytics endpoints for dashboard

## 1) Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

API docs:
- Swagger: `http://127.0.0.1:8001/docs`
- Dashboard UI: `http://127.0.0.1:8001/dashboard`

Vue frontend (recommended for UI work):
```bash
cd frontend
npm install
npm run dev
```
- Vite dev URL: `http://127.0.0.1:5174`
- Dev server proxies API calls to backend at `http://127.0.0.1:8001`

Required env for shared Etsy auth (create `.env` in project root):
```bash
ETSY_API_BASE_URL=http://127.0.0.1:9000/api/v1
ETSY_JWT_SECRET=<same JWT_SECRET as Etsy backend>
ETSY_JWT_ALGORITHM=HS256
AUTH_REQUIRED=true
```
`app/config.py` auto-loads variables from project-root `.env` if present.

Build Vue and serve from FastAPI:
```bash
cd frontend
npm run build
cd ..
uvicorn app.main:app --reload --port 8001
```
- FastAPI auto serves `frontend/dist` at `/dashboard` when build exists.

Quick UI test flow:
- Click `Seed Demo` to generate sample tasks.
- Drag cards across Kanban columns to update status.
- Click a card to open Detail popup tabs: Content, Media, Checklist, Comments, Activity.
- Click `Run Reminders` to trigger `/reminders/run` manually.

Default DB:
- `sqlite:///./social_content.db`
- Override with `DATABASE_URL`

## 1.1) Move to Supabase (shared online DB)

Install Postgres driver:
```bash
pip install -r requirements.txt
```

Set `.env`:
```bash
DATABASE_URL=postgresql+psycopg://postgres:<PASSWORD>@db.<PROJECT-REF>.supabase.co:5432/postgres?sslmode=require
DB_SCHEMA=social
```

Migrate existing SQLite data to Supabase:
```bash
python scripts/migrate_sqlite_to_postgres.py \
  --source sqlite:///./social_content.db \
  --target "postgresql+psycopg://postgres:<PASSWORD>@db.<PROJECT-REF>.supabase.co:5432/postgres?sslmode=require" \
  --target-schema social
```

Optional (clean target first):
```bash
python scripts/migrate_sqlite_to_postgres.py \
  --source sqlite:///./social_content.db \
  --target "postgresql+psycopg://postgres:<PASSWORD>@db.<PROJECT-REF>.supabase.co:5432/postgres?sslmode=require" \
  --target-schema social \
  --truncate-target
```

Run app with Supabase DB:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

## 2) Implemented Modules

### Module A: Core Task Service
- `POST /tasks`
- `GET /tasks`
- `GET /tasks/{id}`
- `PATCH /tasks/{id}`
- `DELETE /tasks/{id}`
- `POST /tasks/{id}/assets`
- `POST /tasks/{id}/validate`
- `POST /tasks/{id}/comments`
- `PUT /tasks/{id}/checklist`
- `GET/POST/PATCH/DELETE /collections`
- `POST /collections/{id}/tasks`
- `DELETE /collections/{id}/tasks/{task_id}`
- `GET/POST/PATCH/DELETE /hashtag-groups`
- `GET/POST/PATCH/DELETE /hashtags`
- `GET /hashtags/suggest`

Includes:
- Audit log per update/delete/comment/asset attach
- Rule-based `validate(task)` by `type`
- Campaign-level `requires_product_url`

### Module B: Chatbot Zalo Interface (webhook)
- `POST /bot/webhook/zalo`
- Commands:
  - `/new`
  - `/set`
  - `/status`
  - `/assign`
  - `/delete <task_id> yes`
  - `/attach <task_id|last>`

### Module D: Reminder Engine
- `POST /reminders/run`
- Jobs are rebuilt when `air_date` is created/updated.
- Milestones (timezone +07):
  - T-3 days: status/progress reminder
  - T-2 days: product URL reminder
  - T-1 day: validate missing fields reminder
  - AirDate 19:00: full post package if valid, else missing fields alert

### Module C: Dashboard API + Vue frontend
- `GET /dashboard/kanban`
- `GET /dashboard/calendar`
- `GET /analytics/basic`
- `POST /auth/login` (proxy to Etsy auth)
- `GET /auth/me`
- `GET /sellers`

Role mapping:
- Etsy `role=admin` => admin features in Social settings.
- Etsy `role=user` => seller (assignee source).

## 3) Validation Rules

`validate(task)` returns:
- `ok: true/false`
- `missing_fields: []`

Required fields by type:
- Story: `title`, `type`, `media>=1`, `air_date`, `status>=ready`, `assignee`, and at least one of `caption|hashtags|mentions`
- Reel/Post: `title`, `type`, `media>=1`, `caption`, `air_date`, `status>=ready`, `assignee`
- `product_url` required only if campaign requires sales URL

## 4) Data Model

Tables:
- `users`
- `campaigns`
- `social_tasks`
- `social_assets`
- `task_comments`
- `task_checklist_items`
- `task_activity_logs`
- `notification_jobs`
- `notification_logs`

## 5) Example API Calls

Create task:
```bash
curl -X POST http://127.0.0.1:8001/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Nick Judy Story",
    "type": "story",
    "air_date": "2026-03-07T19:00:00",
    "status": "idea",
    "campaign_name": "LoveSeason",
    "assignee_name": "Linh",
    "media_urls": ["https://cdn.example.com/a.jpg"]
  }'
```

Validate task:
```bash
curl -X POST http://127.0.0.1:8001/tasks/<TASK_ID>/validate
```

Webhook create via bot:
```bash
curl -X POST http://127.0.0.1:8001/bot/webhook/zalo \
  -H "Content-Type: application/json" \
  -d '{
    "sender_id": "u_001",
    "sender_name": "An",
    "text": "/new story LoveSeason 2026-03-07 19:00 title=Nick_Judy_Story assignee=Linh",
    "media_urls": ["https://cdn.example.com/a.jpg"]
  }'
```

Run reminder jobs:
```bash
curl -X POST http://127.0.0.1:8001/reminders/run \
  -H "Content-Type: application/json" \
  -d '{"limit": 200}'
```

## 6) Notes for Production

- Use Supabase Postgres via `DATABASE_URL`.
- Wire real Zalo send API in reminder dispatch.
- Add auth, RLS, and role permissions.
- Add Alembic later for schema versioning.
- Add dashboard frontend (Kanban/Calendar/Detail/Analytics).
