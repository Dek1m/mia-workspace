"""Workspace Module Configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["WorkspaceConfig"]


@dataclass
class WorkspaceConfig:
    """Конфигурация модуля workspace.

    Приоритет:
    1. Прямые аргументы
    2. Переменные окружения
    """

    # Лимиты по умолчанию
    default_page_size: int = 50
    max_page_size: int = 200
    # Шаблон user-БД. Пустая строка — CREATE DATABASE без TEMPLATE.
    template_database: str = "template_workspace"
    # Корень диска: {fs_root}/{user_hex}/{workspace_id}/
    fs_root: str = "/var/lib/albedo/workspaces"
    # Unix home: {home_root}/{login}/ — корень дерева папок в UI
    home_root: str = "/home"

    @classmethod
    def from_env(cls) -> WorkspaceConfig:
        return cls(
            default_page_size=int(os.getenv("WORKSPACE_DEFAULT_PAGE_SIZE", "50")),
            max_page_size=int(os.getenv("WORKSPACE_MAX_PAGE_SIZE", "200")),
            template_database=os.getenv(
                "WORKSPACE_TEMPLATE_DATABASE", "template_workspace"
            ),
            fs_root=os.getenv("WORKSPACE_FS_ROOT", "/var/lib/albedo/workspaces"),
            home_root=os.getenv("WORKSPACE_HOME_ROOT", "/home"),
        )
