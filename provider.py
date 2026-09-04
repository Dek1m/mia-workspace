"""RPC API workspace для albedo. user из cookie → _session_user_id."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from core.task_decorator import task

from .facade import NotFoundError, WorkspaceAccessor, WorkspaceError

__all__ = ["WorkspaceProvider"]


def _cover(rel: str, linked: set[str], excluded: set[str]) -> str:
    if any(rel == item or rel.startswith(f"{item}/") for item in excluded):
        return "excluded"
    if rel in linked:
        return "linked"
    if any(rel.startswith(f"{parent}/") for parent in linked):
        return "inherited"
    return "none"


class WorkspaceProvider:
    def __init__(
        self,
        accessor: WorkspaceAccessor,
        log: Any | None = None,
        auth: Any | None = None,
        fs: Any | None = None,
    ) -> None:
        self._accessor = accessor
        self._log = log
        self._auth = auth
        self._fs = fs

    def _user(self, session_user_id: str | None) -> str:
        if not session_user_id:
            raise WorkspaceError("Authentication required", "AUTH_ERROR")
        return session_user_id

    def _disk(self) -> Any:
        if self._fs is None:
            raise WorkspaceError("fs module is required", "FS_UNAVAILABLE")
        return self._fs

    def _fs_call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self._disk(), method)(*args, **kwargs)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(code, str) and code:
                raise WorkspaceError(str(exc), code) from exc
            raise

    def _home(self, uid: str) -> str:
        return str(self._fs_call("ensure_home", uid)["home"])

    def _ws(self, uid: str, workspace_id: str) -> Any:
        home = self._home(uid)
        ws = self._accessor(user=uid, ws=workspace_id)
        ws.ensure_root(home)
        return ws

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
        return self._fs_call("ensure_home", self._user(_session_user_id))

    @task(
        type="database",
        api=True,
        name="list_home",
        description="Листинг каталога относительно ~/",
        args={
            "rel_path": "str",
            "workspace_id": "str",
            "include_hidden": "bool",
            "include_size": "bool",
        },
        return_type="dict",
    )
    def list_home(
        self,
        rel_path: str = "",
        workspace_id: str | None = None,
        include_hidden: bool = False,
        include_size: bool = False,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        items = self._fs_call(
            "list", uid, rel_path or "",
            include_hidden=include_hidden, include_size=include_size,
        )
        linked: set[str] = set()
        excluded: set[str] = set()
        if workspace_id:
            ws = self._ws(uid, workspace_id)
            linked = ws.linked_paths()
            excluded = ws.excluded_paths()
        for item in items:
            rel = str(item.get("rel_path") or "")
            cover = _cover(rel, linked, excluded)
            item["linked"] = cover == "linked"
            item["inherited"] = cover == "inherited"
            item["excluded"] = cover == "excluded"
        return {"home": self._fs_call("home_for", uid), "items": items}

    @task(
        type="database",
        api=True,
        name="list_git",
        description="Ветки git для прилинкованных корней workspace",
        args={"workspace_id": "str"},
        return_type="dict",
    )
    def list_git(
        self,
        workspace_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        ws = self._ws(uid, workspace_id)
        roots = sorted(ws.linked_paths()) or [""]
        return {"items": self._fs_call("git_repos", uid, roots)}

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
        parent = parent_rel.strip().lstrip("/")
        rel = f"{parent}/{name.strip()}" if parent else name.strip()
        row = self._fs_call("ensure_nested", uid, rel, kind)
        row["linked"] = False
        return row

    @task(
        type="database",
        api=True,
        name="refresh_home",
        description="Перечитать ~/ и обновить размеры связанных нод",
        args={"workspace_id": "str"},
        return_type="dict",
    )
    def refresh_home(
        self,
        workspace_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        home = Path(self._home(uid))
        updated = 0
        if workspace_id:
            ws = self._ws(uid, workspace_id)
            for item in ws._store.list_all_nodes(ws._id).get("items") or []:
                rel = str(item.get("rel_path") or "")
                if not rel:
                    continue
                path = home / rel
                if not path.exists() or item.get("kind") != "folder":
                    continue
                files, size = self._fs_call("folder_stats", path)
                ws._store.touch_folder_stats(uuid.UUID(str(item["id"])), files, size)
                updated += 1
        return {"home": str(home), "updated": updated}

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
        self._fs_call("register_shareable_root", uid, rel_path)
        return self._ws(uid, workspace_id).link_path(rel_path, create_missing=False)

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
        self._fs_call("unregister_shareable_root", uid, rel_path)
        return self._ws(uid, workspace_id).unlink_path(rel_path)

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
        dest = self._fs_call("trash", uid, rel_path)
        unlinked = 0
        if workspace_id:
            unlinked = self._ws(uid, workspace_id)._unlink_prefix(rel_path.strip().lstrip("/"))
        return {"rel_path": rel_path, "trash_path": dest, "unlinked": unlinked}

    @task(
        type="database",
        api=True,
        name="home_stat",
        description="Тип пути и число детей в каталоге",
        args={"rel_path": "str"},
        return_type="dict",
    )
    def home_stat(
        self,
        rel_path: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        return self._fs_call("stat", self._user(_session_user_id), rel_path)

    @task(
        type="database",
        api=True,
        name="move_home_path",
        description="Перенести путь в другой каталог на диске",
        args={"src": "str", "dest_dir": "str", "workspace_id": "str"},
        return_type="dict",
    )
    def move_home_path(
        self,
        src: str,
        dest_dir: str,
        workspace_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        new_rel = self._fs_call("move", uid, src, dest_dir)
        rewritten = 0
        if workspace_id:
            rewritten = self._ws(uid, workspace_id).rewrite_after_move(
                src.strip().lstrip("/"), new_rel,
            )
        return {"rel_path": new_rel, "rewritten": rewritten}

    @task(
        type="database",
        api=True,
        name="rename_home_path",
        description="Переименовать файл или папку на диске",
        args={"src": "str", "new_name": "str", "workspace_id": "str"},
        return_type="dict",
    )
    def rename_home_path(
        self,
        src: str,
        new_name: str,
        workspace_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        old = src.strip().lstrip("/")
        new_rel = self._fs_call("rename", uid, old, new_name)
        rewritten = 0
        if workspace_id:
            rewritten = self._ws(uid, workspace_id).rewrite_after_move(old, new_rel)
        return {"rel_path": new_rel, "rewritten": rewritten}

    @task(
        type="database",
        api=True,
        name="exclude_home_path",
        description="Исключить вложенный путь из workspace, файлы на диске остаются",
        args={"workspace_id": "str", "rel_path": "str"},
        return_type="dict",
    )
    def exclude_home_path(
        self,
        workspace_id: str,
        rel_path: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        rel = rel_path.strip().lstrip("/")
        ws = self._ws(uid, workspace_id)
        if rel in ws.linked_paths():
            return ws.unlink_path(rel)
        excluded = ws.excluded_paths()
        excluded.add(rel)
        return ws.set_excluded(excluded)

    @task(
        type="database",
        api=True,
        name="include_home_path",
        description="Вернуть исключённый путь в покрытие workspace",
        args={"workspace_id": "str", "rel_path": "str"},
        return_type="dict",
    )
    def include_home_path(
        self,
        workspace_id: str,
        rel_path: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        uid = self._user(_session_user_id)
        rel = rel_path.strip().lstrip("/")
        ws = self._ws(uid, workspace_id)
        excluded = {item for item in ws.excluded_paths() if item != rel}
        return ws.set_excluded(excluded)

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
        return self._ws(uid, workspace_id).trash_node(node_id)

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
        args={"workspace_id": "str", "title": "str", "description": "str"},
        return_type="dict",
    )
    def create_session(
        self,
        workspace_id: str,
        title: str,
        description: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        meta = {"description": description} if description else None
        return ws.create_session(title, metadata=meta)

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
        args={
            "workspace_id": "str",
            "session_id": "str",
            "role": "str",
            "content": "str",
            "agent_name": "str",
            "model_name": "str",
            "parent_id": "str",
        },
        return_type="dict",
    )
    def post_message(
        self,
        workspace_id: str,
        session_id: str,
        role: str,
        content: str,
        agent_name: str | None = None,
        model_name: str | None = None,
        parent_id: str | None = None,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        payload: dict[str, Any] = {}
        if agent_name:
            payload["agent_name"] = agent_name
        if model_name:
            payload["model_name"] = model_name
        if parent_id:
            payload["parent_id"] = parent_id
        return ws.insert_event(session_id, "message", role=role, content=content, payload=payload or None)

    @task(
        type="database",
        api=True,
        name="delete_branch",
        description="Удалить ветку сообщения и всех потомков",
        args={"workspace_id": "str", "session_id": "str", "event_id": "str"},
        return_type="dict",
    )
    def delete_branch(
        self,
        workspace_id: str,
        session_id: str,
        event_id: str,
        _session_user_id: str | None = None,
    ) -> dict[str, Any]:
        ws = self._accessor(user=self._user(_session_user_id), ws=workspace_id)
        return ws.delete_branch(session_id, event_id)
