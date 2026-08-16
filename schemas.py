"""Workspace DB Schema — Schema-first dict для register_schema.

Таблицы workspace, sessions, folders, messages, consiliums, members.
"""
from __future__ import annotations

from typing import Any

__all__ = ["DB_SCHEMA"]

DB_SCHEMA: dict[str, dict[str, Any]] = {
    "schema": "workspace",
    "workspaces": {
        "columns": {
            "owner_id": "UUID NOT NULL REFERENCES auth.users(id)",
            "name": "TEXT NOT NULL",
            "description": "TEXT",
            "settings": "JSONB DEFAULT '{}'::jsonb",
            "is_archived": "BOOLEAN DEFAULT FALSE",
            "created_at": "TIMESTAMPTZ DEFAULT NOW()",
            "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
        },
    },
    "workspace_folders": {
        "columns": {
            "workspace_id": "UUID NOT NULL REFERENCES workspace.workspaces(id) ON DELETE CASCADE",
            "parent_id": "UUID REFERENCES workspace.workspace_folders(id)",
            "name": "TEXT NOT NULL",
            "position": "INTEGER DEFAULT 0",
        },
    },
    "sessions": {
        "columns": {
            "workspace_id": "UUID NOT NULL REFERENCES workspace.workspaces(id) ON DELETE CASCADE",
            "folder_id": "UUID REFERENCES workspace.workspace_folders(id)",
            "title": "TEXT NOT NULL",
            "status": "TEXT DEFAULT 'active'",
            "agent_id": "UUID",
            "metadata": "JSONB DEFAULT '{}'::jsonb",
            "created_at": "TIMESTAMPTZ DEFAULT NOW()",
            "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
        },
    },
    "session_messages": {
        "columns": {
            "session_id": "UUID NOT NULL REFERENCES workspace.sessions(id) ON DELETE CASCADE",
            "role": "TEXT NOT NULL",
            "content": "TEXT",
            "agent_id": "UUID",
            "metadata": "JSONB DEFAULT '{}'::jsonb",
            "created_at": "TIMESTAMPTZ DEFAULT NOW()",
        },
    },
    "agent_consiliums": {
        "columns": {
            "session_id": "UUID NOT NULL REFERENCES workspace.sessions(id) ON DELETE CASCADE",
            "name": "TEXT NOT NULL",
            "agent_ids": "JSONB DEFAULT '[]'::jsonb",
            "status": "TEXT DEFAULT 'pending'",
            "result": "JSONB",
            "created_at": "TIMESTAMPTZ DEFAULT NOW()",
            "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
        },
    },
    "workspace_members": {
        "auto_id": False,
        "primary_key": ["workspace_id", "user_id"],
        "columns": {
            "workspace_id": "UUID NOT NULL REFERENCES workspace.workspaces(id) ON DELETE CASCADE",
            "user_id": "UUID NOT NULL REFERENCES auth.users(id)",
            "role": "TEXT DEFAULT 'viewer'",
            "added_at": "TIMESTAMPTZ DEFAULT NOW()",
        },
    },
}
