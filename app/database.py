from __future__ import annotations

import re

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL, DB_SCHEMA


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
base_engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)


def _resolved_schema() -> str | None:
    schema = (DB_SCHEMA or "").strip()
    if not schema:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("invalid_db_schema")
    return schema


resolved_schema = _resolved_schema()

if resolved_schema and base_engine.dialect.name == "postgresql":
    engine = base_engine.execution_options(schema_translate_map={None: resolved_schema})
else:
    engine = base_engine

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
