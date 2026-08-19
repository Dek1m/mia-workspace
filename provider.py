"""Workspace Provider — основной провайдер модуля workspace."""
from __future__ import annotations

from typing import Any


from modules.auth.decorators import auth_method

from .config import WorkspaceConfig
from .repository import WorkspaceRepository
from .schema import WORKSPACE_SCHEMA
from .schemas import DB_SCHEMA


__all__ = ["WorkspaceProvider"]


class WorkspaceError(Exception):
    """Базовая ошибка workspace-модуля."""

    def __init__(self, message: str, code: str = "WORKSPACE_ERROR") -> None:
        self.code = code
        super().__init__(message)


class ForbiddenError(WorkspaceError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message, "FORBIDDEN")


class NotFoundError(WorkspaceError):
    def __init__(self, entity: str = "Resource") -> None:
        super().__init__(f"{entity} not found", "NOT_FOUND")


class WorkspaceProvider:
    """Провайдер workspace.

    Предоставляет CRUD для workspace, папок, сессий, сообщений,
    консилиумов и участников. Проверяет владение/членство.
    """

    def __init__(self, config: WorkspaceConfig, database: Any, log: Any = None) -> None:
        self._config = config
        self._database = database
        self._log = log
        self._repo = WorkspaceRepository(database, log=log)

    @property
    def repository(self) -> WorkspaceRepository:
        return self._repo

    async def initialize(self, state: Any) -> None:
        """Регистрация БД-схемы и AUTH_SCHEMA."""
        # Регистрация БД-схемы (идемпотентно)
        from modules.db.provider import DatabaseProvider

        db_provider = state.services.resolve(DatabaseProvider)
        await db_provider.register_schema(
            "workspace",
            DB_SCHEMA,
            schema_name="workspace",
            ddl_dir="ddl",
        )

        # Регистрация AUTH_SCHEMA
        from modules.auth.schema_registry import AuthSchemaRegistry

        auth_registry = state.services.resolve(AuthSchemaRegistry)
        await auth_registry.register("workspace", WORKSPACE_SCHEMA, is_builtin=False)

        self._log.info("Workspace schema registered")

    # ── Workspaces ──────────────────────────────────────

    @auth_method(
        name="create_workspace",
        description="Создать рабочее пространство",
        args={"name": "str", "description": "str", "settings": "dict"},
        return_type="dict",
        public=False,
        required_permission="workspace:create",
    )
    async def create_workspace(
        self,
        owner_id: str,
        name: str,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._repo.create_workspace(owner_id, name, description, settings)

    @auth_method(
        name="get_workspace",
        description="Получить workspace по ID",
        args={"workspace_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:read",
    )
    async def get_workspace(self, workspace_id: str, user_id: str) -> dict[str, Any]:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if not await self._repo.user_can_access(workspace_id, user_id):
            raise ForbiddenError("Access denied")
        return ws

    @auth_method(
        name="list_workspaces",
        description="Список workspace пользователя",
        args={"owner_id": "str", "offset": "int", "limit": "int"},
        return_type="dict",
        public=False,
        required_permission="workspace:list",
    )
    async def list_workspaces(
        self,
        owner_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        items, total = await self._repo.list_workspaces(owner_id, offset, limit)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    @auth_method(
        name="update_workspace",
        description="Обновить workspace",
        args={"workspace_id": "str", "data": "dict"},
        return_type="dict",
        public=False,
        required_permission="workspace:update",
    )
    async def update_workspace(
        self, workspace_id: str, data: dict[str, Any], user_id: str,
    ) -> dict[str, Any]:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if not await self._repo.user_can_access(workspace_id, user_id):
            raise ForbiddenError("Access denied")
        result = await self._repo.update_workspace(workspace_id, data)
        if not result:
            raise NotFoundError("Workspace")
        return result

    @auth_method(
        name="delete_workspace",
        description="Удалить workspace",
        args={"workspace_id": "str"},
        return_type="bool",
        public=False,
        required_permission="workspace:delete",
    )
    async def delete_workspace(self, workspace_id: str, user_id: str) -> bool:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if ws["owner_id"] != user_id:
            raise ForbiddenError("Only owner can delete workspace")
        return await self._repo.delete_workspace(workspace_id)

    @auth_method(
        name="archive_workspace",
        description="Архивировать workspace",
        args={"workspace_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:update",
    )
    async def archive_workspace(self, workspace_id: str, user_id: str) -> dict[str, Any]:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if not await self._repo.user_can_access(workspace_id, user_id):
            raise ForbiddenError("Access denied")
        result = await self._repo.archive_workspace(workspace_id)
        if not result:
            raise NotFoundError("Workspace")
        return result

    # ── Members ─────────────────────────────────────────

    @auth_method(
        name="add_member",
        description="Добавить участника в workspace",
        args={"workspace_id": "str", "user_id": "str", "role": "str"},
        return_type="None",
        public=False,
        required_permission="workspace:member_manage",
    )
    async def add_member(
        self, workspace_id: str, user_id: str, role: str = "viewer",
        operator_id: str | None = None,
    ) -> None:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if not await self._repo.user_can_access(workspace_id, operator_id or user_id):
            raise ForbiddenError("Access denied")
        await self._repo.add_member(workspace_id, user_id, role)

    @auth_method(
        name="remove_member",
        description="Удалить участника из workspace",
        args={"workspace_id": "str", "user_id": "str"},
        return_type="bool",
        public=False,
        required_permission="workspace:member_manage",
    )
    async def remove_member(self, workspace_id: str, user_id: str) -> bool:
        return await self._repo.remove_member(workspace_id, user_id)

    @auth_method(
        name="list_members",
        description="Список участников workspace",
        args={"workspace_id": "str"},
        return_type="list",
        public=False,
        required_permission="workspace:read",
    )
    async def list_members(self, workspace_id: str) -> list[dict[str, Any]]:
        return await self._repo.list_members(workspace_id)

    # ── Sessions ────────────────────────────────────────

    @auth_method(
        name="create_session",
        description="Создать сессию в workspace",
        args={"workspace_id": "str", "title": "str", "folder_id": "str", "agent_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_create",
    )
    async def create_session(
        self,
        workspace_id: str,
        title: str,
        user_id: str,
        folder_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ws = await self._repo.get_workspace(workspace_id)
        if not ws:
            raise NotFoundError("Workspace")
        if not await self._repo.user_can_access(workspace_id, user_id):
            raise ForbiddenError("Access denied")
        return await self._repo.create_session(workspace_id, title, folder_id, agent_id, metadata)

    @auth_method(
        name="list_sessions",
        description="Список сессий workspace",
        args={"workspace_id": "str", "offset": "int", "limit": "int"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_read",
    )
    async def list_sessions(
        self, workspace_id: str, offset: int = 0, limit: int = 50,
    ) -> dict[str, Any]:
        items, total = await self._repo.list_sessions(workspace_id, offset, limit)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    @auth_method(
        name="get_session",
        description="Получить сессию по ID",
        args={"session_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_read",
    )
    async def get_session(self, session_id: str) -> dict[str, Any]:
        session = await self._repo.get_session(session_id)
        if not session:
            raise NotFoundError("Session")
        return session

    # ── Messages ────────────────────────────────────────

    @auth_method(
        name="add_message",
        description="Добавить сообщение в сессию",
        args={"session_id": "str", "role": "str", "content": "str", "agent_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_create",
    )
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._repo.add_message(session_id, role, content, agent_id, metadata)

    @auth_method(
        name="list_messages",
        description="Список сообщений сессии",
        args={"session_id": "str", "offset": "int", "limit": "int"},
        return_type="list",
        public=False,
        required_permission="workspace:session_read",
    )
    async def list_messages(
        self, session_id: str, offset: int = 0, limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_messages(session_id, offset, limit)

    # ── Consiliums ──────────────────────────────────────

    @auth_method(
        name="create_consilium",
        description="Создать консилиум агентов",
        args={"session_id": "str", "name": "str", "agent_ids": "list"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_create",
    )
    async def create_consilium(
        self,
        session_id: str,
        name: str,
        agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._repo.create_consilium(session_id, name, agent_ids)

    @auth_method(
        name="get_consilium",
        description="Получить консилиум по ID",
        args={"consilium_id": "str"},
        return_type="dict",
        public=False,
        required_permission="workspace:session_read",
    )
    async def get_consilium(self, consilium_id: str) -> dict[str, Any]:
        consilium = await self._repo.get_consilium(consilium_id)
        if not consilium:
            raise NotFoundError("Consilium")
        return consilium

    @auth_method(
        name="list_consiliums",
        description="Список консилиумов сессии",
        args={"session_id": "str"},
        return_type="list",
        public=False,
        required_permission="workspace:session_read",
    )
    async def list_consiliums(self, session_id: str) -> list[dict[str, Any]]:
        return await self._repo.list_consiliums(session_id)
