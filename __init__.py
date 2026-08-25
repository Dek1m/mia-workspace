"""Workspace Module — per-user PostgreSQL database + product workspaces.

Публичный контракт:
    state.workspace(user=uuid|User, ws=uuid)        → Workspace
    state.workspace(user=...).list()                → JSON список пространств
    state.workspace(user=..., ws=...).sessions()    → JSON сессии
    state.workspace(user=..., ws=...).sessions(sid) → JSON лента events
"""
from __future__ import annotations

from typing import Any

from modules_system.module_base import ModuleBase, ModuleMeta

from .config import WorkspaceConfig
from .facade import (
    NotFoundError,
    UserWorkspaces,
    Workspace,
    WorkspaceAccessor,
    WorkspaceError,
)
from .provider import WorkspaceProvider

__all__ = [
    "WorkspaceModule",
    "WorkspaceConfig",
    "WorkspaceAccessor",
    "UserWorkspaces",
    "Workspace",
    "WorkspaceError",
    "NotFoundError",
    "WorkspaceProvider",
]

MODULE_VERSION = "2.3.0"


class WorkspaceModule(ModuleBase):
    """Домен workspace: фасад на state, схема на named user-БД."""

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
            cache_rules={},
            timeout_defaults={},
        )

    def __init__(self, config: WorkspaceConfig | None = None) -> None:
        self._config = config or WorkspaceConfig.from_env()
        self._log = None
        self._provider: WorkspaceProvider | None = None

    def on_load(self, state: Any) -> None:
        """Вешает state.workspace. Схему user-БД накатывает фасад при первом заходе."""
        self._log = state.log
        from modules.db.provider import DatabaseProvider

        database = state.services.resolve(DatabaseProvider)
        accessor = WorkspaceAccessor(
            database=database, log=self._log, config=self._config,
        )
        state.workspace = accessor
        auth = None
        try:
            from modules.auth.provider import AuthProvider

            auth = state.services.resolve(AuthProvider)
        except Exception:
            auth = None
        self._provider = WorkspaceProvider(accessor, self._log, auth)
        state.services.register(WorkspaceProvider, self._provider)
        self._register_auth_schema(state)
        self._log.info("WorkspaceModule loaded", extra={"version": self.version})

    def on_unload(self) -> None:
        if self._log is not None:
            self._log.info("WorkspaceModule unloaded")
        self._provider = None
        self._log = None

    def _register_auth_schema(self, state: Any) -> None:
        """Permissions живут в auth. Нет — фасад всё равно работает."""
        try:
            from modules.auth.schema_registry import AuthSchemaRegistry
            from .schema import WORKSPACE_SCHEMA

            registry = state.services.resolve(AuthSchemaRegistry)
            registry.register_sync("workspace", WORKSPACE_SCHEMA, is_builtin=False)
        except Exception as exc:
            if self._log is not None:
                self._log.debug(
                    "workspace auth schema skipped",
                    extra={"error": str(exc)},
                )
