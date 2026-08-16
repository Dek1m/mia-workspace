"""Workspace Module — управление проектами для Mia Framework.

Предоставляет:
- Управление рабочими пространствами (workspace CRUD)
- Папки, сессии, сообщения, консилиумы
- Участники workspace с ролями (owner/manager/viewer)
- Интеграцию с auth (permissions) и LLM (консилиумы — Фаза 6)

Использование:
    app.load_module("workspace")

    provider = app.services.resolve(WorkspaceProvider)
    ws = await provider.create_workspace(owner_id="u1", name="My Project")
"""
from __future__ import annotations

from typing import Any

from modules_system.module_base import ModuleBase

from .config import WorkspaceConfig
from .provider import WorkspaceProvider

__all__ = [
    "WorkspaceModule",
    "WorkspaceProvider",
    "WorkspaceConfig",
]

from argenta_logging import get_logger

log = get_logger(__name__)

MODULE_VERSION = "1.0.0"


class WorkspaceModule(ModuleBase):
    """Workspace-модуль для Mia Framework.

    Предоставляет:
    - Управление рабочими пространствами
    - Папки, сессии, сообщения, консилиумы
    - Участники с ролями
    """

    @property
    def name(self) -> str:
        return "workspace"

    @property
    def version(self) -> str:
        return MODULE_VERSION

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self._config = config or WorkspaceConfig.from_env()
        self._provider: WorkspaceProvider | None = None

    def on_load(self, state: Any) -> None:
        """Инициализация модуля: pool → repository → register_schema → register_auth_schema → провайдер."""
        import asyncio

        # Получаем пул БД из DatabaseProvider
        from modules.db.provider import DatabaseProvider

        db_provider = state.services.resolve(DatabaseProvider)
        pool = db_provider.pool

        # Создаём провайдер
        self._provider = WorkspaceProvider(config=self._config, pool=pool)

        # Регистрация в DI
        state.services.register(WorkspaceProvider, self._provider)

        # Инициализация БД + AUTH_SCHEMA (идемпотентно)
        async def _init_workspace() -> None:
            await self._provider.initialize(state)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_init_workspace())
        else:
            loop.run_until_complete(_init_workspace())

        log.info("WorkspaceModule loaded", version=self.version)

    def on_unload(self) -> None:
        """Очистка ресурсов."""
        log.info("WorkspaceModule unloaded")
