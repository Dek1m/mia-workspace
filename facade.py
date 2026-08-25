"""Фасад state.workspace(...) — единственная Python-точка входа.

SQL домена — только функции schema workspace.* из ddl/003_functions.sql.
Провижининг user-БД идёт через db.create_database / get_pool / register_schema.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import WorkspaceConfig
from .fs import (
    FsError,
    ensure_dir,
    folder_stats,
    join_rel,
    mkdir,
    remove,
    safe_name,
    touch,
    trash_move,
    workspace_dir,
)
from .schemas import DB_SCHEMA, TEMPLATE_DATABASE, user_dbname, uuid_hex

__all__ = [
    "WorkspaceAccessor",
    "UserWorkspaces",
    "Workspace",
    "WorkspaceError",
    "NotFoundError",
]


class WorkspaceError(Exception):
    """Ошибка фасада workspace."""

    def __init__(self, message: str, code: str = "WORKSPACE_ERROR") -> None:
        self.code = code
        super().__init__(message)


class NotFoundError(WorkspaceError):
    def __init__(self, entity: str = "Resource") -> None:
        super().__init__(f"{entity} not found", "NOT_FOUND")


def _user_id(user: str | Any) -> str:
    if isinstance(user, str):
        return user
    value = getattr(user, "uuid", None)
    if not isinstance(value, str) or not value:
        raise WorkspaceError(f"Invalid user: {user!r}", "INVALID_USER")
    return value


def _as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(hex=uuid_hex(value))
    except ValueError as exc:
        raise WorkspaceError(f"Invalid UUID: {value!r}", "INVALID_UUID") from exc


def _as_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode()
    if isinstance(value, str):
        return json.loads(value)
    return value


def _same_uuid(left: Any, right: uuid.UUID) -> bool:
    if left is None:
        return False
    try:
        return _as_uuid(str(left)) == right
    except WorkspaceError:
        return False


def _is_duplicate_db(exc: BaseException) -> bool:
    pgcode = getattr(exc, "pgcode", None)
    if pgcode == "42P04":
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and getattr(cause, "pgcode", None) == "42P04":
        return True
    return "already exists" in str(exc).lower()


def _info(log: Any, message: str, **extra: Any) -> None:
    if log is None:
        return
    log.info(message, extra=extra)


class UserStore:
    """Открытая user-БД: SELECT workspace.* только."""

    def __init__(self, pool: Any, dbname: str, user_hex: str, fs_root: str) -> None:
        self.pool = pool
        self.dbname = dbname
        self.user_hex = user_hex
        self.fs_root = fs_root

    def list_workspaces(self, include_archived: bool, limit: int, offset: int) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.list_workspaces(%s, %s, %s)",
            (include_archived, limit, offset),
        )
        return row or {"items": [], "total": 0, "limit": limit, "offset": offset}

    def get_workspace(self, workspace_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.get_workspace(%s)", (workspace_id,))

    def create_workspace(
        self, name: str, description: str | None, settings: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.create_workspace(%s, %s, %s::jsonb)",
            (name, description, json.dumps(settings or {})),
        )
        if not isinstance(row, dict):
            raise WorkspaceError("create_workspace returned empty", "DATABASE_ERROR")
        return row

    def list_sessions(
        self, workspace_id: uuid.UUID, status: str | None, limit: int, offset: int,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.list_sessions(%s, %s, %s, %s)",
            (workspace_id, status, limit, offset),
        )
        return row or {
            "items": [], "total": 0, "limit": limit, "offset": offset,
        }

    def get_session(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.get_session(%s)", (session_id,))

    def create_session(
        self,
        workspace_id: uuid.UUID,
        title: str,
        agent_id: uuid.UUID | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.create_session(%s, %s, %s, %s::jsonb)",
            (workspace_id, title, agent_id, json.dumps(metadata or {})),
        )
        if not isinstance(row, dict):
            raise WorkspaceError("create_session returned empty", "DATABASE_ERROR")
        return row

    def fetch_timeline(
        self, session_id: uuid.UUID, before: datetime | None, limit: int,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.fetch_timeline(%s, %s, %s)",
            (session_id, before, limit),
        )
        return row or {
            "items": [],
            "session_id": str(session_id),
            "limit": limit,
            "has_more": False,
        }

    def insert_event(
        self,
        session_id: uuid.UUID,
        kind: str,
        role: str | None,
        content: str | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.insert_event(%s, %s, %s, %s, %s::jsonb, %s, %s)",
            (session_id, kind, role, content, json.dumps(payload or {}), None, None),
        )
        if not isinstance(row, dict):
            raise WorkspaceError("insert_event returned empty", "DATABASE_ERROR")
        return row

    def delete_workspace(self, workspace_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.delete_workspace(%s)", (workspace_id,))

    def set_workspace_root(self, workspace_id: uuid.UUID, root: str) -> dict[str, Any] | None:
        return self._fetch(
            "SELECT workspace.set_workspace_root(%s, %s)", (workspace_id, root),
        )

    def delete_session(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.delete_session(%s)", (session_id,))

    def set_session_flags(
        self,
        session_id: uuid.UUID,
        tab_open: bool | None,
        agent_busy: bool | None,
    ) -> dict[str, Any] | None:
        return self._fetch(
            "SELECT workspace.set_session_flags(%s, %s, %s)",
            (session_id, tab_open, agent_busy),
        )

    def close_all_tabs(self, workspace_id: uuid.UUID) -> dict[str, Any]:
        row = self._fetch("SELECT workspace.close_all_tabs(%s)", (workspace_id,))
        return row or {"closed": 0}

    def create_node(
        self,
        workspace_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        kind: str,
        name: str,
        rel_path: str,
        size_bytes: int,
        file_count: int,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.create_node(%s, %s, %s, %s, %s, %s, %s)",
            (workspace_id, parent_id, kind, name, rel_path, size_bytes, file_count),
        )
        if not isinstance(row, dict):
            raise WorkspaceError("create_node returned empty", "DATABASE_ERROR")
        return row

    def list_nodes(
        self, workspace_id: uuid.UUID, parent_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        row = self._fetch(
            "SELECT workspace.list_nodes(%s, %s)", (workspace_id, parent_id),
        )
        return row or {"items": []}

    def get_node(self, node_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.get_node(%s)", (node_id,))

    def get_node_by_path(
        self, workspace_id: uuid.UUID, rel_path: str,
    ) -> dict[str, Any] | None:
        return self._fetch(
            "SELECT workspace.get_node_by_path(%s, %s)", (workspace_id, rel_path),
        )

    def list_all_nodes(self, workspace_id: uuid.UUID) -> dict[str, Any]:
        row = self._fetch("SELECT workspace.list_all_nodes(%s)", (workspace_id,))
        return row or {"items": []}

    def delete_node(self, node_id: uuid.UUID) -> dict[str, Any] | None:
        return self._fetch("SELECT workspace.delete_node(%s)", (node_id,))

    def touch_folder_stats(
        self, node_id: uuid.UUID, file_count: int, size_bytes: int,
    ) -> None:
        self._fetch(
            "SELECT workspace.touch_folder_stats(%s, %s, %s)",
            (node_id, file_count, size_bytes),
        )

    def _fetch(self, query: str, params: tuple[Any, ...]) -> Any:
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
        except WorkspaceError:
            raise
        except Exception as exc:
            from argenta_logging import get_logger

            get_logger(__name__).error(
                "workspace_query_failed",
                extra={"dbname": self.dbname, "error_type": type(exc).__name__},
            )
            raise WorkspaceError(str(exc), "DATABASE_ERROR") from exc
        if row is None:
            return None
        return _as_json(row[0])


class WorkspaceCatalog:
    """Провижининг: 1 PostgreSQL database на пользователя, схема на named pool."""

    def __init__(self, database: Any, log: Any, config: WorkspaceConfig) -> None:
        self._database = database
        self._log = log
        self._config = config
        self._ready: set[str] = set()
        self._guard = threading.Lock()
        self._db_locks: dict[str, threading.Lock] = {}

    def open(self, user: str | Any) -> UserStore:
        try:
            hex_id = uuid_hex(_user_id(user))
        except ValueError as exc:
            raise WorkspaceError(str(exc), "INVALID_UUID") from exc
        dbname = user_dbname(hex_id)
        self._ensure(dbname, hex_id)
        pool = self._database.get_pool(dbname)
        return UserStore(
            pool=pool,
            dbname=dbname,
            user_hex=hex_id,
            fs_root=self._config.fs_root,
        )

    def _ensure(self, dbname: str, user_hex: str) -> None:
        with self._guard:
            if dbname in self._ready:
                return
            lock = self._db_locks.setdefault(dbname, threading.Lock())
        with lock:
            if dbname in self._ready:
                return
            self._provision(dbname, user_hex)
            with self._guard:
                self._ready.add(dbname)

    def _provision(self, dbname: str, user_hex: str) -> None:
        created = False
        if not self._db_exists(dbname):
            template = self._template_if_exists()
            self._create_user_db(dbname, template)
            created = True
            _info(
                self._log, "user database created",
                dbname=dbname, user_id=user_hex, template=template,
            )
        pool = self._database.get_pool(dbname)
        self._database.register_schema(
            "workspace",
            dict(DB_SCHEMA),
            schema_name="workspace",
            ddl_dir="ddl",
            pool=pool,
        )
        _info(
            self._log, "user database opened",
            dbname=dbname, user_id=user_hex, created=created,
        )

    def _db_exists(self, dbname: str) -> bool:
        pool = self._database.get_system_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                return cur.fetchone() is not None

    def _template_if_exists(self) -> str | None:
        name = self._config.template_database or TEMPLATE_DATABASE
        if not name:
            return None
        return name if self._db_exists(name) else None

    def _create_user_db(self, dbname: str, template: str | None) -> None:
        try:
            self._database.create_database(dbname, template=template)
        except Exception as exc:
            if _is_duplicate_db(exc) and self._db_exists(dbname):
                return
            raise


class WorkspaceAccessor:
    """state.workspace — callable фасад."""

    def __init__(self, database: Any, log: Any, config: WorkspaceConfig) -> None:
        self._catalog = WorkspaceCatalog(database, log, config)
        self._config = config
        self._log = log

    def __call__(
        self, *, user: str | Any, ws: str | None = None,
    ) -> UserWorkspaces | Workspace:
        store = self._catalog.open(user)
        if ws is None:
            return UserWorkspaces(store, self._config, self._log)
        return Workspace(store, ws, self._config, self._log)


class UserWorkspaces:
    """Пространства пользователя. Product ws — строка, не CREATE DATABASE."""

    def __init__(self, store: UserStore, config: WorkspaceConfig, log: Any) -> None:
        self._store = store
        self._config = config
        self._log = log

    def list(
        self,
        include_archived: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        page = _page(limit, self._config.default_page_size, self._config.max_page_size)
        result = self._store.list_workspaces(include_archived, page, offset)
        _info(
            self._log, "workspaces listed",
            dbname=self._store.dbname,
            total=result.get("total"),
            limit=result.get("limit"),
            offset=result.get("offset"),
        )
        return result

    def create(
        self,
        name: str,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
        folders: list[str] | None = None,
        home: str | None = None,
    ) -> dict[str, Any]:
        row = self._store.create_workspace(name, description, settings)
        ws_id = str(row.get("id"))
        root = Path(home) if home else workspace_dir(
            self._store.fs_root, self._store.user_hex, ws_id,
        )
        ensure_dir(root)
        updated = self._store.set_workspace_root(uuid.UUID(ws_id), str(root))
        if isinstance(updated, dict):
            row = updated
        ws = Workspace(self._store, ws_id, self._config, self._log)
        for folder in folders or []:
            rel = str(folder).strip().lstrip("/")
            if not rel:
                continue
            ws.link_path(rel, create_missing=True)
        _info(
            self._log, "workspace created",
            dbname=self._store.dbname,
            workspace_id=row.get("id"),
        )
        return row

    def delete(self, workspace_id: str) -> dict[str, Any]:
        ws = Workspace(self._store, workspace_id, self._config, self._log)
        root = ws.disk_root()
        home_root = Path(self._config.home_root).resolve()
        try:
            root.resolve().relative_to(home_root)
        except ValueError:
            try:
                remove(root, "")
            except FsError:
                pass
        row = self._store.delete_workspace(ws._id)
        if not isinstance(row, dict):
            raise NotFoundError("Workspace")
        _info(self._log, "workspace deleted", workspace_id=ws.id)
        return row


class Workspace:
    """Один продуктовый workspace внутри user-БД."""

    def __init__(
        self, store: UserStore, workspace_id: str, config: WorkspaceConfig, log: Any,
    ) -> None:
        self._store = store
        self._id = _as_uuid(workspace_id)
        self._config = config
        self._log = log
        data = store.get_workspace(self._id)
        if not isinstance(data, dict):
            raise NotFoundError("Workspace")
        self._data = data

    @property
    def id(self) -> str:
        return str(self._id)

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def sessions(
        self,
        session_id: str | None = None,
        *,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        before: datetime | None = None,
    ) -> dict[str, Any]:
        if session_id is None:
            return self._list_sessions(status, limit, offset)
        return self._timeline(session_id, limit, before)

    def delete(self) -> dict[str, Any]:
        return UserWorkspaces(self._store, self._config, self._log).delete(self.id)

    def disk_root(self) -> Path:
        stored = self._data.get("root_path")
        if stored:
            return Path(str(stored))
        return workspace_dir(self._store.fs_root, self._store.user_hex, self.id)

    def ensure_root(self, home: str) -> None:
        """Корень диска — ~/ пользователя, не старый workspace_dir."""
        target = Path(home).resolve()
        current = self.disk_root()
        try:
            if current.resolve() == target:
                return
        except OSError:
            pass
        ensure_dir(target)
        updated = self._store.set_workspace_root(self._id, str(target))
        if isinstance(updated, dict):
            self._data = updated
        else:
            self._data["root_path"] = str(target)

    def nodes(self, parent_id: str | None = None) -> dict[str, Any]:
        parent = _as_uuid(parent_id) if parent_id else None
        return self._store.list_nodes(self._id, parent)

    def link_path(self, rel: str, create_missing: bool = False) -> dict[str, Any]:
        """Привязать существующий путь под root (~/) к дереву workspace."""
        rel = rel.strip().lstrip("/")
        if not rel or ".." in rel:
            raise WorkspaceError("invalid path", "INVALID_NAME")
        root = self.disk_root()
        ensure_dir(root)
        path = join_rel(root, rel)
        if not path.exists():
            if not create_missing:
                raise WorkspaceError("path not found", "NOT_FOUND")
            mkdir(root, rel)
            path = join_rel(root, rel)
        kind = "folder" if path.is_dir() else "file"
        name = path.name
        files, size = folder_stats(path) if kind == "folder" else (0, path.stat().st_size)
        row = self._store.create_node(
            self._id, None, kind, name, rel, size, files if kind == "folder" else 0,
        )
        _info(self._log, "node linked", workspace_id=self.id, rel=rel)
        return row

    def create_folder(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        return self._create_node("folder", name, parent_id)

    def create_file(self, name: str, parent_id: str | None = None) -> dict[str, Any]:
        return self._create_node("file", name, parent_id)

    def delete_node(self, node_id: str) -> dict[str, Any]:
        """Убрать из проекта. Файлы на диске остаются."""
        return self._unlink_id(node_id)

    def unlink_path(self, rel: str) -> dict[str, Any]:
        rel = rel.strip().lstrip("/")
        node = self._store.get_node_by_path(self._id, rel)
        if not isinstance(node, dict):
            raise NotFoundError("Node")
        return self._unlink_id(str(node["id"]))

    def trash_node(self, node_id: str) -> dict[str, Any]:
        node = self._store.get_node(_as_uuid(node_id))
        if not isinstance(node, dict) or not _same_uuid(node.get("workspace_id"), self._id):
            raise NotFoundError("Node")
        rel = str(node.get("rel_path") or "")
        return self.trash_path(rel)

    def trash_path(self, rel: str) -> dict[str, Any]:
        """Перенести в ~/Trash/belle/ и отвязать все ноды под этим путём."""
        rel = rel.strip().lstrip("/")
        root = self.disk_root()
        try:
            dest = trash_move(root, rel)
        except FsError as exc:
            raise WorkspaceError(str(exc), exc.code) from exc
        removed = self._unlink_prefix(rel)
        _info(self._log, "path trashed", workspace_id=self.id, rel=rel, dest=dest)
        return {"rel_path": rel, "trash_path": dest, "unlinked": removed}

    def linked_paths(self) -> set[str]:
        items = self._store.list_all_nodes(self._id).get("items") or []
        return {str(item.get("rel_path")) for item in items if item.get("rel_path")}

    def _unlink_id(self, node_id: str) -> dict[str, Any]:
        nid = _as_uuid(node_id)
        node = self._store.get_node(nid)
        if not isinstance(node, dict) or not _same_uuid(node.get("workspace_id"), self._id):
            raise NotFoundError("Node")
        row = self._store.delete_node(nid)
        if not isinstance(row, dict):
            raise NotFoundError("Node")
        _info(self._log, "node unlinked", workspace_id=self.id, node_id=str(nid))
        return row

    def _unlink_prefix(self, rel: str) -> int:
        items = self._store.list_all_nodes(self._id).get("items") or []
        count = 0
        for item in items:
            path = str(item.get("rel_path") or "")
            if path == rel or path.startswith(rel + "/"):
                row = self._store.delete_node(_as_uuid(str(item["id"])))
                if isinstance(row, dict):
                    count += 1
        return count

    def _create_node(self, kind: str, name: str, parent_id: str | None) -> dict[str, Any]:
        clean = safe_name(name)
        parent = _as_uuid(parent_id) if parent_id else None
        rel = clean
        if parent is not None:
            parent_row = self._store.get_node(parent)
            if not isinstance(parent_row, dict) or not _same_uuid(
                parent_row.get("workspace_id"), self._id,
            ):
                raise NotFoundError("Folder")
            rel = f"{parent_row['rel_path']}/{clean}"
        root = self.disk_root()
        ensure_dir(root)
        try:
            if kind == "folder":
                mkdir(root, rel)
            else:
                touch(root, rel)
        except FsError as exc:
            raise WorkspaceError(str(exc), exc.code) from exc
        path = root / rel
        files, size = folder_stats(path) if kind == "folder" else (0, path.stat().st_size)
        row = self._store.create_node(
            self._id, parent, kind, clean, rel, size, files if kind == "folder" else 0,
        )
        _info(self._log, "node created", workspace_id=self.id, kind=kind)
        return row

    def delete_session(self, session_id: str) -> dict[str, Any]:
        sid = self._require_session(session_id)
        row = self._store.delete_session(sid)
        if not isinstance(row, dict):
            raise NotFoundError("Session")
        _info(self._log, "session deleted", workspace_id=self.id, session_id=str(sid))
        return row

    def open_session(self, session_id: str) -> dict[str, Any]:
        return self._flags(session_id, tab_open=True)

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self._flags(session_id, tab_open=False)

    def set_agent_busy(self, session_id: str, busy: bool) -> dict[str, Any]:
        return self._flags(session_id, agent_busy=busy)

    def close_all_tabs(self) -> dict[str, Any]:
        result = self._store.close_all_tabs(self._id)
        _info(self._log, "tabs closed", workspace_id=self.id)
        return result

    def _flags(
        self,
        session_id: str,
        tab_open: bool | None = None,
        agent_busy: bool | None = None,
    ) -> dict[str, Any]:
        sid = self._require_session(session_id)
        row = self._store.set_session_flags(sid, tab_open, agent_busy)
        if not isinstance(row, dict):
            raise NotFoundError("Session")
        return row

    def create_session(
        self,
        title: str,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        agent = _as_uuid(agent_id) if agent_id else None
        row = self._store.create_session(self._id, title, agent, metadata)
        _info(
            self._log, "session created",
            workspace_id=str(self._id),
            session_id=row.get("id"),
        )
        return row

    def insert_event(
        self,
        session_id: str,
        kind: str,
        role: str | None = None,
        content: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        row = self._store.insert_event(session, kind, role, content, payload)
        _info(
            self._log, "event inserted",
            workspace_id=str(self._id),
            session_id=str(session),
            kind=kind,
        )
        return row

    def _list_sessions(
        self, status: str | None, limit: int | None, offset: int,
    ) -> dict[str, Any]:
        page = _page(limit, self._config.default_page_size, self._config.max_page_size)
        result = self._store.list_sessions(self._id, status, page, offset)
        _info(
            self._log, "sessions listed",
            workspace_id=str(self._id),
            total=result.get("total"),
            limit=result.get("limit"),
            offset=result.get("offset"),
        )
        return result

    def _timeline(
        self, session_id: str, limit: int | None, before: datetime | None,
    ) -> dict[str, Any]:
        session = self._require_session(session_id)
        page = _page(limit, 100, self._config.max_page_size)
        result = self._store.fetch_timeline(session, before, page)
        _info(
            self._log, "timeline fetched",
            workspace_id=str(self._id),
            session_id=str(session),
            limit=result.get("limit"),
            has_more=result.get("has_more"),
        )
        return result

    def _require_session(self, session_id: str) -> uuid.UUID:
        sid = _as_uuid(session_id)
        row = self._store.get_session(sid)
        if not isinstance(row, dict) or not _same_uuid(row.get("workspace_id"), self._id):
            raise NotFoundError("Session")
        return sid


def _page(limit: int | None, default: int, maximum: int) -> int:
    size = default if limit is None else limit
    if size < 0:
        return 0
    return min(size, maximum)
