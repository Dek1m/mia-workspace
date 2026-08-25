"""RPC API workspace для albedo. user из cookie → _session_user_id."""
from __future__ import annotations

from typing import Any

from core.task_decorator import task

from .facade import NotFoundError, WorkspaceAccessor, WorkspaceError

__all__ = ["WorkspaceProvider"]


class WorkspaceProvider:
    def __init__(self, accessor: WorkspaceAccessor, log: Any | None = None) -> None:
        self._accessor = accessor
        self._log = log

    def _user(self, session_user_id: str | None) -> str:
        if not session_user_id:
            raise WorkspaceError("Authentication required", "AUTH_ERROR")
        return session_user_id

    @task(
        type="database",
        api=True,
        name="list_workspaces",
        description="Список пространств текущего пользователя",
        args={"include_archived": "bool"},
        return_type="dict",
    )
    def list_workspaces(
        self,
        include_archived: bool = False,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self._accessor(user=self._user(_session_user_id)).list(
            include_archived=include_archived,
        )

    @task(
        type="database",
        api=True,
        name="create_workspace",
        description="Создать пространство. folders — необязательные имена корневых папок",
        args={"name": "str", "description": "str", "folders": "list"},
        return_type="dict",
    )
    def create_workspace(
        self,
        name: str,
        description: str | None = None,
        folders: list[str] | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self._accessor(user=self._user(_session_user_id)).create(
            name, description, folders=folders,
        )

    @task(
        type="database",
        api=True,
        name="delete_workspace",
        description="Удалить пространство и файлы на диске",
        args={"workspace_id": "str"},
        return_type="dict",
    )
    def delete_workspace(
        self,
        workspace_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self._accessor(user=self._user(_session_user_id)).delete(workspace_id)

    @task(
        type="database",
        api=True,
        name="get_workspace",
        description="Одно пространство",
        args={"workspace_id": "str"},
        return_type="dict",
    )
    def get_workspace(
        self,
        workspace_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.data

    @task(
        type="database",
        api=True,
        name="list_nodes",
        description="Дети папки. parent_id пустой — корень",
        args={"workspace_id": "str", "parent_id": "str"},
        return_type="dict",
    )
    def list_nodes(
        self,
        workspace_id: str,
        parent_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.nodes(parent_id)

    @task(
        type="database",
        api=True,
        name="create_folder",
        description="Создать папку на диске и запись в БД",
        args={"workspace_id": "str", "name": "str", "parent_id": "str"},
        return_type="dict",
    )
    def create_folder(
        self,
        workspace_id: str,
        name: str,
        parent_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.create_folder(name, parent_id)

    @task(
        type="database",
        api=True,
        name="create_file",
        description="Создать файл на диске и запись в БД",
        args={"workspace_id": "str", "name": "str", "parent_id": "str"},
        return_type="dict",
    )
    def create_file(
        self,
        workspace_id: str,
        name: str,
        parent_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.create_file(name, parent_id)

    @task(
        type="database",
        api=True,
        name="delete_node",
        description="Удалить папку или файл",
        args={"workspace_id": "str", "node_id": "str"},
        return_type="dict",
    )
    def delete_node(
        self,
        workspace_id: str,
        node_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.delete_node(node_id)

    @task(
        type="database",
        api=True,
        name="list_sessions",
        description="Сессии пространства",
        args={"workspace_id": "str", "status": "str"},
        return_type="dict",
    )
    def list_sessions(
        self,
        workspace_id: str,
        status: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.sessions(status=status)

    @task(
        type="database",
        api=True,
        name="create_session",
        description="Создать сессию (вкладка закрыта, агент idle)",
        args={"workspace_id": "str", "title": "str"},
        return_type="dict",
    )
    def create_session(
        self,
        workspace_id: str,
        title: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.create_session(title)

    @task(
        type="database",
        api=True,
        name="delete_session",
        description="Удалить сессию и ленту",
        args={"workspace_id": "str", "session_id": "str"},
        return_type="dict",
    )
    def delete_session(
        self,
        workspace_id: str,
        session_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.delete_session(session_id)

    @task(
        type="database",
        api=True,
        name="open_session",
        description="Открыть вкладку. Агент не останавливается",
        args={"workspace_id": "str", "session_id": "str"},
        return_type="dict",
    )
    def open_session(
        self,
        workspace_id: str,
        session_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.open_session(session_id)

    @task(
        type="database",
        api=True,
        name="close_session",
        description="Закрыть вкладку. Агент продолжает работу",
        args={"workspace_id": "str", "session_id": "str"},
        return_type="dict",
    )
    def close_session(
        self,
        workspace_id: str,
        session_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.close_session(session_id)

    @task(
        type="database",
        api=True,
        name="close_all_tabs",
        description="Закрыть все вкладки пространства",
        args={"workspace_id": "str"},
        return_type="dict",
    )
    def close_all_tabs(
        self,
        workspace_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.close_all_tabs()

    @task(
        type="database",
        api=True,
        name="set_agent_busy",
        description="Флаг активности агента в сессии",
        args={"workspace_id": "str", "session_id": "str", "busy": "bool"},
        return_type="dict",
    )
    def set_agent_busy(
        self,
        workspace_id: str,
        session_id: str,
        busy: bool,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.set_agent_busy(session_id, busy)

    @task(
        type="database",
        api=True,
        name="list_messages",
        description="Лента сообщений сессии",
        args={"workspace_id": "str", "session_id": "str"},
        return_type="dict",
    )
    def list_messages(
        self,
        workspace_id: str,
        session_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.sessions(session_id)

    @task(
        type="database",
        api=True,
        name="post_message",
        description="Сообщение user|assistant. UUID пишет БД",
        args={"workspace_id": "str", "session_id": "str", "role": "str", "content": "str"},
        return_type="dict",
    )
    def post_message(
        self,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.insert_event(session_id, "message", role=role, content=content)
