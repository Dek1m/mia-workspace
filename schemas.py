"""Workspace DB Schema — per-user PostgreSQL database.

Эта схема живёт НЕ в системной БД belle, а в отдельной БД пользователя.

Имя БД задаёт модуль workspace (не db и не ядро):
    belle_workspace_{uuid_hex}
где uuid_hex — user id без дефисов (32 hex-символа). Дефисы запрещены:
PostgreSQL identifier, алфавит [a-z0-9_].

Внутри БД три сущности: workspaces, sessions, events.
events — единая лента (сообщения + действия), дискриминатор kind.
Партиции RANGE по created_at (месяц UTC) создаёт ddl/002_events.sql:
register_schema умеет только CREATE TABLE (...), без PARTITION BY.

Нет FK на auth.users. Владелец БД — граница database, не колонка.
owner_id в таблицах нет: 1 БД = 1 пользователь.

Формат Schema-first: dict с ключом "columns", как у auth.
Ключ "schema" указывает PostgreSQL-схему для всех таблиц.
"""
from __future__ import annotations

from typing import Any

__all__ = ["DB_SCHEMA", "DB_NAME_PREFIX", "TEMPLATE_DATABASE", "uuid_hex", "user_dbname"]

# Префикс имени per-user БД. uuid в имени — hex без дефисов.
DB_NAME_PREFIX = "belle_workspace_"
TEMPLATE_DATABASE = "template_workspace"

_HEX = frozenset("0123456789abcdef")


def uuid_hex(value: str) -> str:
    """UUID → 32 hex-символа без дефисов. Иначе PostgreSQL identifier сломается."""
    if not isinstance(value, str):
        raise ValueError(f"Invalid UUID: {value!r}")
    hex_id = value.replace("-", "").lower()
    if len(hex_id) != 32 or any(ch not in _HEX for ch in hex_id):
        raise ValueError(f"Invalid UUID: {value!r}")
    return hex_id


def user_dbname(user_id: str) -> str:
    """Имя per-user PostgreSQL database: belle_workspace_{uuid_hex}."""
    return f"{DB_NAME_PREFIX}{uuid_hex(user_id)}"

DB_SCHEMA: dict[str, dict[str, Any]] = {
    "schema": "workspace",

    # ── Продуктовые пространства (папки) внутри user-БД ──
    # CREATE DATABASE на каждый workspace НЕ вызывается.
    "workspaces": {
        "columns": {
            "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
            "name": "VARCHAR(255) NOT NULL",
            "description": "TEXT",
            "settings": "JSONB NOT NULL DEFAULT '{}'::jsonb",
            "is_archived": "BOOLEAN NOT NULL DEFAULT FALSE",
            "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        },
    },

    # ── Сессии внутри пространства ────────────────────────
    "sessions": {
        "columns": {
            "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
            "workspace_id": "UUID NOT NULL REFERENCES workspace.workspaces(id) ON DELETE CASCADE",
            "title": "TEXT NOT NULL",
            "status": "VARCHAR(20) NOT NULL DEFAULT 'active'",
            "agent_id": "UUID",
            "metadata": "JSONB NOT NULL DEFAULT '{}'::jsonb",
            "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        },
    },

    # ── Лента: сообщения и действия в одной таблице ───────
    # PK составной: партиции RANGE требуют, чтобы ключ партиции
    # входил в PRIMARY KEY. register_schema создаст кучу;
    # ddl/002_events.sql идемпотентно сменит её на PARTITION BY RANGE (created_at).
    # Append-only: updated_at нет, правки ленты — новые события.
    "events": {
        "auto_id": False,
        "primary_key": ["id", "created_at"],
        "columns": {
            "id": "UUID NOT NULL DEFAULT gen_random_uuid()",
            "session_id": "UUID NOT NULL REFERENCES workspace.sessions(id) ON DELETE CASCADE",
            "kind": "VARCHAR(32) NOT NULL",
            "role": "VARCHAR(32)",
            "content": "TEXT",
            "payload": "JSONB NOT NULL DEFAULT '{}'::jsonb",
            "created_at": "TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        },
    },
}
