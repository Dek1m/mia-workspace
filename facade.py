"""Фасад state.workspace(...) — единственная Python-точка входа.

SQL домена — только функции schema workspace.* из ddl/003_functions.sql.
Провижининг user-БД идёт через db.create_database / get_pool / register_schema.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any

from .config import WorkspaceConfig
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

    def __init__(self, pool: Any, dbname: str) -> None:
        self.pool = pool
        self.dbname = dbname

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

    def _fetch(self, query: str, params: tuple[Any, ...]) -> Any:
        try:
            with self.pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
        except WorkspaceError:
            raise
        except Exception as exc:
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
        return UserStore(pool=pool, dbname=dbname)

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
    ) -> dict[str, Any]:
        row = self._store.create_workspace(name, description, settings)
        _info(
            self._log, "workspace created",
            dbname=self._store.dbname,
            workspace_id=row.get("id"),
        )
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
