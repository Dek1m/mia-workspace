"""RPC API workspace для albedo. user из cookie → _session_user_id."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

from core.task_decorator import task

from pathlib import Path

from .facade import NotFoundError, WorkspaceAccessor, WorkspaceError
from .fs import mkdir, safe_name, touch, trash_move
from .homes import ensure_unix_home, list_home, unix_name

__all__ = ["WorkspaceProvider"]


def _run_coro(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=10)


class WorkspaceProvider:
    def __init__(
        self,
        accessor: WorkspaceAccessor,
        log: Any | None = None,
        auth: Any | None = None,
    ) -> None:
        self._accessor = accessor
        self._log = log
        self._auth = auth

    def _user(self, session_user_id: str | None) -> str:
        if not session_user_id:
            raise WorkspaceError("Authentication required", "AUTH_ERROR")
        return session_user_id

    def _unix(self, uid: str) -> str:
        raw = uid
        if self._auth is not None:
            try:
                fn = inspect.unwrap(self._auth.get_user)
                if inspect.iscoroutinefunction(fn):
                    row = _run_coro(fn(self._auth, uid))
                else:
                    row = fn(self._auth, uid)
                if isinstance(row, dict) and row.get("username"):
                    raw = str(row["username"])
            except Exception:
                raw = uid
        return unix_name(raw)

    def _home(self, uid: str) -> str:
        return ensure_unix_home(self._unix(uid), self._accessor._config.home_root)

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
        uid = self._user(_session_user_id)
        return self._accessor(user=uid).create(
            name, description, folders=folders, home=self._home(uid),
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
        name="ensure_home",
        description="Создать unix-пользователя и ~/ если ещё нет",
        args={},
        return_type="dict",
    )
    def ensure_home(self, _session_user_id: str | None = None) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        home = self._home(uid)
        return {"home": home, "username": self._unix(uid)}

    @task(
        type="database",
        api=True,
        name="list_home",
        description="Листинг каталога относительно ~/",
        args={"rel_path": "str", "workspace_id": "str"},
        return_type="dict",
    )
    def list_home(
        self,
        rel_path: str = "",
        workspace_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        home = self._home(uid)
        items = list_home(home, rel_path or "")
        linked: set[str] = set()
        if workspace_id:
            linked = self._accessor(user=uid, ws=workspace_id).linked_paths()
        for item in items:
            item["linked"] = item.get("rel_path") in linked
        return {"home": home, "items": items}

    @task(
        type="database",
        api=True,
        name="create_home_path",
        description="Создать папку или файл в ~/ на диске контейнера",
        args={"name": "str", "parent_rel": "str", "kind": "str"},
        return_type="dict",
    )
    def create_home_path(
        self,
        name: str,
        parent_rel: str = "",
        kind: str = "folder",
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"folder", "file"}:
            raise WorkspaceError("invalid kind", "INVALID_NAME")
        uid = self._user(_session_user_id)
        home = Path(self._home(uid))
        clean = safe_name(name)
        parent = parent_rel.strip().lstrip("/")
        rel = f"{parent}/{clean}" if parent else clean
        if kind == "folder":
            mkdir(home, rel)
        else:
            touch(home, rel)
        return {"name": clean, "kind": kind, "rel_path": rel, "linked": False}

    @task(
        type="database",
        api=True,
        name="link_home_path",
        description="Привязать путь из ~/ к workspace",
        args={"workspace_id": "str", "rel_path": "str"},
        return_type="dict",
    )
    def link_home_path(
        self,
        workspace_id: str,
        rel_path: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        self._home(uid)
        ws = self._accessor(user=uid, ws=workspace_id)
        return ws.link_path(rel_path, create_missing=False)

    @task(
        type="database",
        api=True,
        name="unlink_home_path",
        description="Убрать путь из проекта. Файлы на диске остаются",
        args={"workspace_id": "str", "rel_path": "str"},
        return_type="dict",
    )
    def unlink_home_path(
        self,
        workspace_id: str,
        rel_path: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        ws = self._accessor(user=uid, ws=workspace_id)
        return ws.unlink_path(rel_path)

    @task(
        type="database",
        api=True,
        name="trash_home_path",
        description="Перенести путь в ~/Trash/belle/ и отвязать от проекта",
        args={"rel_path": "str", "workspace_id": "str"},
        return_type="dict",
    )
    def trash_home_path(
        self,
        rel_path: str,
        workspace_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        home = self._home(uid)
        if workspace_id:
            return self._accessor(user=uid, ws=workspace_id).trash_path(rel_path)
        dest = trash_move(Path(home), rel_path)
        return {"rel_path": rel_path, "trash_path": dest, "unlinked": 0}

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
        description="Убрать ноду из проекта. Файлы на диске остаются",
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
        name="trash_node",
        description="Перенести ноду в ~/Trash/belle/ и отвязать",
        args={"workspace_id": "str", "node_id": "str"},
        return_type="dict",
    )
    def trash_node(
        self,
        workspace_id: str,
        node_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        self._home(uid)
        ws = self._accessor(user=uid, ws=workspace_id)
        return ws.trash_node(node_id)

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
