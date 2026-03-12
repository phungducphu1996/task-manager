#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql.sqltypes import DateTime as SADateTime
from sqlalchemy.sql.sqltypes import JSON as SAJSON

DEFAULT_SOURCE_URL = "sqlite:///./social_content.db"
# Force local SQLite for importing app modules in this migration script.
# Target Postgres connection is handled explicitly by --target.
os.environ["DATABASE_URL"] = DEFAULT_SOURCE_URL

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base

# Ensure model tables are registered on Base.metadata.
import app.models  # noqa: F401

TABLE_ORDER = [
    "users",
    "campaigns",
    "collections",
    "social_tasks",
    "task_collection_links",
    "social_assets",
    "task_comments",
    "task_checklist_items",
    "task_activity_logs",
    "hashtag_groups",
    "hashtags_library",
    "notification_jobs",
    "notification_logs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Social Tasker data from SQLite to Postgres (Supabase)."
    )
    parser.add_argument(
        "--source",
        default=os.getenv("MIGRATION_SOURCE_URL", DEFAULT_SOURCE_URL),
        help=f"Source database URL (default: {DEFAULT_SOURCE_URL})",
    )
    parser.add_argument(
        "--target",
        default=os.getenv("MIGRATION_TARGET_URL", os.getenv("DATABASE_URL", "")),
        help="Target Postgres URL. Uses MIGRATION_TARGET_URL or DATABASE_URL if omitted.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Rows per insert batch (default: 500)",
    )
    parser.add_argument(
        "--target-schema",
        default=os.getenv("DB_SCHEMA", "").strip(),
        help="Target Postgres schema (default: DB_SCHEMA env or public if empty).",
    )
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="Delete existing target data before copy.",
    )
    return parser.parse_args()


def _chunked(rows: list[dict], size: int) -> Iterable[list[dict]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _parse_datetime(value: str) -> datetime | str:
    raw = value.strip()
    if not raw:
        return value
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return value


def _coerce_value(value, target_column):
    if value is None:
        return None

    if isinstance(target_column.type, SAJSON) and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    if isinstance(target_column.type, SADateTime) and isinstance(value, str):
        return _parse_datetime(value)

    return value


def _prepare_row(table_name: str, source_row: dict, target_table) -> dict:
    prepared: dict = {}
    for column in target_table.columns:
        name = column.name
        if name in source_row:
            prepared[name] = _coerce_value(source_row.get(name), column)

    if table_name == "campaigns":
        if not prepared.get("status"):
            prepared["status"] = "planning"
        if not prepared.get("updated_at"):
            prepared["updated_at"] = prepared.get("created_at") or datetime.now(timezone.utc)

    return prepared


def _insert_rows(target_conn, target_table, rows: list[dict], chunk_size: int, dialect_name: str) -> int:
    if not rows:
        return 0
    inserted = 0
    pk_columns = [column.name for column in target_table.primary_key.columns]
    for batch in _chunked(rows, chunk_size):
        if dialect_name == "postgresql":
            stmt = pg_insert(target_table).values(batch)
            if pk_columns:
                stmt = stmt.on_conflict_do_nothing(index_elements=pk_columns)
            result = target_conn.execute(stmt)
        else:
            result = target_conn.execute(target_table.insert(), batch)
        if result.rowcount and result.rowcount > 0:
            inserted += result.rowcount
    return inserted


def _normalize_schema_name(value: str | None) -> str | None:
    schema = (value or "").strip()
    if not schema:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise SystemExit(f"Invalid schema name: {schema}")
    return schema


def migrate(source_url: str, target_url: str, chunk_size: int, target_schema: str | None, truncate_target: bool) -> None:
    if not target_url:
        raise SystemExit("Missing --target (or MIGRATION_TARGET_URL / DATABASE_URL).")
    normalized_schema = _normalize_schema_name(target_schema)

    source_engine = create_engine(source_url, future=True)
    target_base_engine = create_engine(target_url, future=True)
    target_engine = (
        target_base_engine.execution_options(schema_translate_map={None: normalized_schema})
        if normalized_schema
        else target_base_engine
    )

    if source_engine.dialect.name != "sqlite":
        raise SystemExit(f"Unsupported source dialect: {source_engine.dialect.name}. Expected sqlite.")
    if target_base_engine.dialect.name != "postgresql":
        raise SystemExit(f"Unsupported target dialect: {target_base_engine.dialect.name}. Expected postgresql.")

    if normalized_schema:
        with target_base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{normalized_schema}"'))

    source_meta = MetaData()
    source_meta.reflect(bind=source_engine)

    Base.metadata.create_all(bind=target_engine)
    target_meta = Base.metadata

    with target_engine.begin() as target_conn:
        if truncate_target:
            print("Truncating target tables...")
            for table_name in reversed(TABLE_ORDER):
                table = target_meta.tables.get(table_name)
                if table is not None:
                    target_conn.execute(table.delete())

        with source_engine.connect() as source_conn:
            for table_name in TABLE_ORDER:
                source_table = source_meta.tables.get(table_name)
                target_table = target_meta.tables.get(table_name)
                if source_table is None or target_table is None:
                    print(f"Skipping {table_name}: table not available in source/target")
                    continue

                common_columns = [name for name in source_table.c.keys() if name in target_table.c.keys()]
                if not common_columns:
                    print(f"Skipping {table_name}: no shared columns")
                    continue

                select_columns = [source_table.c[name] for name in common_columns]
                source_rows = source_conn.execute(select(*select_columns)).mappings().all()
                if table_name == "task_comments":
                    # Parent comments first to satisfy self-referenced FK.
                    source_rows = sorted(source_rows, key=lambda row: (row.get("parent_id") is not None, row.get("created_at") or ""))
                prepared_rows = [_prepare_row(table_name, dict(row), target_table) for row in source_rows]
                inserted = _insert_rows(
                    target_conn=target_conn,
                    target_table=target_table,
                    rows=prepared_rows,
                    chunk_size=max(1, chunk_size),
                    dialect_name=target_base_engine.dialect.name,
                )
                print(f"{table_name}: source={len(source_rows)} inserted={inserted}")


def main() -> None:
    args = parse_args()
    migrate(
        source_url=args.source,
        target_url=args.target,
        chunk_size=args.chunk_size,
        target_schema=args.target_schema,
        truncate_target=args.truncate_target,
    )
    print("Migration done.")


if __name__ == "__main__":
    main()
