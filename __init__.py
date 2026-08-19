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

from modules_system.module_base import ModuleBase, ModuleMeta

from .config import WorkspaceConfig
from .provider import WorkspaceProvider

__all__ = [
    "WorkspaceModule",
    "WorkspaceProvider",
    "WorkspaceConfig",
]

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

    @property
    def meta(self) -> ModuleMeta:
        return ModuleMeta(
            dependencies=["log", "db"],
            cache_rules={"get_workspace": 60, "get_session": 60},
            timeout_defaults={"create_workspace": 10.0, "create_session": 10.0},
        )

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self._config = config or WorkspaceConfig.from_env()
        self._provider: WorkspaceProvider | None = None
        self._log = None

    def on_load(self, state: Any) -> None:
        """Инициализация модуля: pool → repository → register_schema → register_auth_schema → провайдер."""
        self._log = state.log
        import asyncio

        # Получаем пул БД из DatabaseProvider
        from modules.db.provider import DatabaseProvider

        db_provider = state.services.resolve(DatabaseProvider)
        database = db_provider

        # Создаём провайдер
        self._provider = WorkspaceProvider(config=self._config, database=database, log=self._log)

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

        self._log.info("WorkspaceModule loaded", version=self.version)

    def on_unload(self) -> None:
        """Очистка ресурсов."""
        self._log.info("WorkspaceModule unloaded")
        self._log = None
