"""Фикстуры фасада workspace — sync-моки пула и DatabaseProvider."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

USER_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
USER_HEX = "aaaaaaaabbbbccccddddeeeeeeeeeeee"
WS_UUID = "11111111-1111-1111-1111-111111111111"
SESSION_UUID = "22222222-2222-2222-2222-222222222222"


class RecordingLog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, Any]]] = []

    def _store(self, level: str, message: str, extra: dict[str, Any] | None = None) -> None:
        self.records.append((level, message, extra or {}))

    def debug(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self._store("debug", message, extra)

    def info(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self._store("info", message, extra)

    def warning(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self._store("warning", message, extra)

    def error(self, message: str, extra: dict[str, Any] | None = None) -> None:
        self._store("error", message, extra)

    def messages(self) -> list[str]:
        return [item[1] for item in self.records]


class _Cursor:
    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool
        self._row: tuple[Any, ...] | None = None

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        self._row = self._pool.owner.dispatch(self._pool.name, query, params or ())

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class _Connection:
    def __init__(self, pool: "FakePool") -> None:
        self._pool = pool

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self._pool)


class FakePool:
    def __init__(self, name: str, owner: "FakeDatabase") -> None:
        self.name = name
        self.owner = owner
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def connection(self) -> _Connection:
        return _Connection(self)


class FakeDatabase:
    """Мок DatabaseProvider: system/named пулы, create_database, register_schema."""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.databases: set[str] = set(existing or set())
        self.created: list[tuple[str, str | None]] = []
        self.schema_calls: list[dict[str, Any]] = []
        self.system = FakePool("belle", self)
        self.named: dict[str, FakePool] = {}
        self.workspaces: dict[str, dict[str, dict[str, Any]]] = {}
        self.sessions: dict[str, dict[str, dict[str, Any]]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}

    def get_system_pool(self) -> FakePool:
        return self.system

    def get_pool(self, dbname: str) -> FakePool:
        if dbname == "belle":
            return self.system
        if dbname not in self.named:
            self.named[dbname] = FakePool(dbname, self)
        return self.named[dbname]

    def create_database(self, dbname: str, *, template: str | None = None) -> None:
        if dbname in self.databases:
            err = RuntimeError(f'database "{dbname}" already exists')
            err.pgcode = "42P04"  # type: ignore[attr-defined]
            raise err
        self.created.append((dbname, template))
        self.databases.add(dbname)

    def register_schema(self, db_name: str, schemas: dict[str, Any], **kwargs: Any) -> None:
        self.schema_calls.append({"db_name": db_name, "schemas": schemas, **kwargs})

    def dispatch(
        self, pool_name: str, query: str, params: tuple[Any, ...],
    ) -> tuple[Any, ...] | None:
        if pool_name == "belle":
            self.system.queries.append((query, params))
        elif pool_name in self.named:
            self.named[pool_name].queries.append((query, params))
        if "pg_database" in query:
            datname = params[0] if params else None
            return (1,) if datname in self.databases else None
        match = re.search(r"workspace\.(\w+)", query)
        if match is None:
            raise AssertionError(f"unexpected query on {pool_name}: {query}")
        payload = self._call(pool_name, match.group(1), params)
        return (payload,)

    def _call(self, dbname: str, func: str, params: tuple[Any, ...]) -> Any:
        table_ws = self.workspaces.setdefault(dbname, {})
        table_ss = self.sessions.setdefault(dbname, {})
        table_ev = self.events.setdefault(dbname, [])
        table_nd = self.nodes.setdefault(dbname, {})
        if func == "list_workspaces":
            items = list(table_ws.values())
            return {"items": items, "total": len(items), "limit": params[1], "offset": params[2]}
        if func == "get_workspace":
            return table_ws.get(str(params[0]))
        if func == "create_workspace":
            row = {
                "id": WS_UUID if not table_ws else str(uuid.uuid4()),
                "name": params[0],
                "description": params[1],
                "settings": json.loads(params[2]) if isinstance(params[2], str) else params[2],
                "is_archived": False,
                "root_path": None,
            }
            table_ws[row["id"]] = row
            return row
        if func == "set_workspace_root":
            row = table_ws.get(str(params[0]))
            if row is None:
                return None
            row["root_path"] = params[1]
            return row
        if func == "delete_workspace":
            return table_ws.pop(str(params[0]), None)
        if func == "list_sessions":
            items = [s for s in table_ss.values() if s["workspace_id"] == str(params[0])]
            return {"items": items, "total": len(items), "limit": params[2], "offset": params[3]}
        if func == "get_session":
            return table_ss.get(str(params[0]))
        if func == "create_session":
            row = {
                "id": SESSION_UUID,
                "workspace_id": str(params[0]),
                "title": params[1],
                "status": "active",
                "agent_id": str(params[2]) if params[2] else None,
                "tab_open": False,
                "agent_busy": False,
            }
            table_ss[row["id"]] = row
            return row
        if func == "delete_session":
            return table_ss.pop(str(params[0]), None)
        if func == "set_session_flags":
            row = table_ss.get(str(params[0]))
            if row is None:
                return None
            if params[1] is not None:
                row["tab_open"] = params[1]
            if params[2] is not None:
                row["agent_busy"] = params[2]
            return row
        if func == "close_all_tabs":
            n = 0
            for sess in table_ss.values():
                if sess.get("workspace_id") == str(params[0]) and sess.get("tab_open"):
                    sess["tab_open"] = False
                    n += 1
            return {"closed": n}
        if func == "create_node":
            row = {
                "id": str(uuid.uuid4()),
                "workspace_id": str(params[0]),
                "parent_id": str(params[1]) if params[1] else None,
                "kind": params[2],
                "name": params[3],
                "rel_path": params[4],
                "size_bytes": params[5],
                "file_count": params[6],
            }
            table_nd[row["id"]] = row
            return row
        if func == "list_nodes":
            parent = str(params[1]) if params[1] else None
            items = [
                n for n in table_nd.values()
                if n["workspace_id"] == str(params[0]) and n.get("parent_id") == parent
            ]
            return {"items": items}
        if func == "get_node":
            return table_nd.get(str(params[0]))
        if func == "delete_node":
            return table_nd.pop(str(params[0]), None)
        if func == "touch_folder_stats":
            return None
        if func == "fetch_timeline":
            items = [e for e in table_ev if e["session_id"] == str(params[0])]
            return {
                "items": items,
                "session_id": str(params[0]),
                "limit": params[2],
                "has_more": False,
            }
        if func == "insert_event":
            row = {
                "id": str(uuid.uuid4()),
                "session_id": str(params[0]),
                "kind": params[1],
                "role": params[2],
                "content": params[3],
                "payload": json.loads(params[4]) if isinstance(params[4], str) else params[4],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            table_ev.append(row)
            return row
        raise AssertionError(f"unknown function {func}")


class FakeUser:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid


@pytest.fixture
def log() -> RecordingLog:
    return RecordingLog()


@pytest.fixture
def database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def accessor(database: FakeDatabase, log: RecordingLog, tmp_path):
    from modules.workspace.config import WorkspaceConfig
    from modules.workspace.facade import WorkspaceAccessor

    return WorkspaceAccessor(
        database=database,
        log=log,
        config=WorkspaceConfig(home_root=str(tmp_path)),
    )
