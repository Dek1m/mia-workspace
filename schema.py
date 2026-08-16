"""Workspace AUTH_SCHEMA — permissions и roles для модуля workspace.

Регистрация через AuthSchemaRegistry.register("workspace", WORKSPACE_SCHEMA).
"""
from __future__ import annotations

from typing import Any

__all__ = ["WORKSPACE_SCHEMA"]

WORKSPACE_SCHEMA: dict[str, list[dict[str, Any]]] = {
    "permissions": [
        {"name": "workspace:create", "description": "Создание рабочих пространств"},
        {"name": "workspace:read", "description": "Чтение данных workspace"},
        {"name": "workspace:update", "description": "Обновление workspace"},
        {"name": "workspace:delete", "description": "Удаление workspace"},
        {"name": "workspace:list", "description": "Получение списка workspace"},
        {"name": "workspace:member_manage", "description": "Управление участниками workspace"},
        {"name": "workspace:session_create", "description": "Создание сессий"},
        {"name": "workspace:session_read", "description": "Чтение сессий и сообщений"},
    ],
    "roles": [
        {
            "name": "workspace_manager",
            "description": "Полное управление workspace",
            "permissions": [
                "workspace:*",
                "workspace:member_manage",
                "workspace:session_create",
                "workspace:session_read",
            ],
        },
        {
            "name": "workspace_viewer",
            "description": "Только чтение workspace и сессий",
            "permissions": [
                "workspace:read",
                "workspace:list",
                "workspace:session_read",
            ],
        },
    ],
}
