"""Тесты фасада state.workspace — контракт Мастера, провижининг, SQL API."""
from __future__ import annotations

import pytest

from modules.workspace.config import WorkspaceConfig
from modules.workspace.facade import (
    NotFoundError,
    UserWorkspaces,
    Workspace,
    WorkspaceAccessor,
    WorkspaceError,
)
from modules.workspace.schemas import DB_NAME_PREFIX, user_dbname
from modules.workspace.tests.conftest import (
    SESSION_UUID,
    USER_HEX,
    USER_UUID,
    WS_UUID,
    FakeDatabase,
    FakeUser,
    RecordingLog,
)

DBNAME = f"{DB_NAME_PREFIX}{USER_HEX}"


def test_user_dbname_hex_without_hyphens() -> None:
    assert user_dbname(USER_UUID) == DBNAME
    assert "-" not in user_dbname(USER_UUID)
    assert user_dbname(USER_HEX) == DBNAME


def test_list_creates_user_db_without_template(
    accessor: WorkspaceAccessor, database: FakeDatabase, log: RecordingLog,
) -> None:
    result = accessor(user=USER_UUID).list()
    assert result["total"] == 0
    assert database.created == [(DBNAME, None)]
    assert database.schema_calls[0]["pool"] is database.named[DBNAME]
    assert database.schema_calls[0]["db_name"] == "workspace"
    assert "user database created" in log.messages()
    assert "user database opened" in log.messages()
    assert "workspaces listed" in log.messages()


def test_list_uses_template_when_present(
    log: RecordingLog,
) -> None:
    database = FakeDatabase(existing={"template_workspace"})
    accessor = WorkspaceAccessor(
        database=database, log=log, config=WorkspaceConfig(),
    )
    accessor(user=USER_UUID).list()
    assert database.created == [(DBNAME, "template_workspace")]


def test_second_open_does_not_create_again(
    accessor: WorkspaceAccessor, database: FakeDatabase,
) -> None:
    accessor(user=USER_UUID).list()
    accessor(user=USER_UUID).list()
    assert len(database.created) == 1
    assert len(database.schema_calls) == 1


def test_user_object_same_as_uuid_string(
    accessor: WorkspaceAccessor, database: FakeDatabase,
) -> None:
    accessor(user=FakeUser(USER_UUID)).list()
    assert database.created[0][0] == DBNAME


def test_invalid_uuid_rejected(accessor: WorkspaceAccessor) -> None:
    with pytest.raises((WorkspaceError, ValueError)):
        accessor(user="not-a-uuid").list()


def test_create_and_list_workspaces(
    accessor: WorkspaceAccessor, log: RecordingLog,
) -> None:
    bag = accessor(user=USER_UUID)
    assert isinstance(bag, UserWorkspaces)
    created = bag.create("Inbox")
    listed = bag.list()
    assert created["name"] == "Inbox"
    assert listed["total"] == 1
    assert created.get("root_path")
    extras = [extra for _, msg, extra in log.records if msg == "workspaces listed"]
    assert extras and "items" not in extras[0]


def test_workspace_object_and_sessions(
    accessor: WorkspaceAccessor, log: RecordingLog,
) -> None:
    accessor(user=USER_UUID).create("Inbox")
    ws = accessor(user=USER_UUID, ws=WS_UUID)
    assert isinstance(ws, Workspace)
    assert ws.data["name"] == "Inbox"
    session = ws.create_session("Debug")
    listed = ws.sessions()
    assert session["title"] == "Debug"
    assert listed["total"] == 1
    extras = [extra for _, msg, extra in log.records if msg == "sessions listed"]
    assert extras and "items" not in extras[0]


def test_sessions_timeline_does_not_log_content(
    accessor: WorkspaceAccessor, log: RecordingLog,
) -> None:
    accessor(user=USER_UUID).create("Inbox")
    ws = accessor(user=USER_UUID, ws=WS_UUID)
    ws.create_session("Debug")
    ws.insert_event(SESSION_UUID, "message", role="user", content="secret-body")
    timeline = ws.sessions(SESSION_UUID)
    assert timeline["items"][0]["content"] == "secret-body"
    extras = [extra for _, msg, extra in log.records if msg == "timeline fetched"]
    assert extras
    blob = str(extras[0])
    assert "secret-body" not in blob
    assert "items" not in extras[0]


def test_folder_on_disk_and_session_tabs(
    accessor: WorkspaceAccessor, tmp_path,
) -> None:
    bag = accessor(user=USER_UUID)
    created = bag.create("Inbox", folders=["docs"])
    ws = accessor(user=USER_UUID, ws=created["id"])
    nodes = ws.nodes()
    assert any(n["name"] == "docs" and n["kind"] == "folder" for n in nodes["items"])
    session = ws.create_session("Chat")
    opened = ws.open_session(session["id"])
    assert opened["tab_open"] is True
    closed = ws.close_session(session["id"])
    assert closed["tab_open"] is False
    busy = ws.set_agent_busy(session["id"], True)
    assert busy["agent_busy"] is True


def test_workspace_not_found(accessor: WorkspaceAccessor) -> None:
    with pytest.raises(NotFoundError):
        accessor(user=USER_UUID, ws=WS_UUID)


def test_session_from_other_workspace_not_found(accessor: WorkspaceAccessor) -> None:
    accessor(user=USER_UUID).create("Inbox")
    ws = accessor(user=USER_UUID, ws=WS_UUID)
    with pytest.raises(NotFoundError):
        ws.sessions("33333333-3333-3333-3333-333333333333")


def test_named_pool_sql_is_only_workspace_functions(
    accessor: WorkspaceAccessor, database: FakeDatabase,
) -> None:
    bag = accessor(user=USER_UUID)
    bag.create("Inbox")
    ws = accessor(user=USER_UUID, ws=WS_UUID)
    ws.create_session("Debug")
    ws.sessions()
    ws.sessions(SESSION_UUID)
    queries = database.named[DBNAME].queries
    assert queries
    for query, _params in queries:
        assert query.startswith("SELECT workspace.")
        assert "FROM workspace.workspaces" not in query
        assert "INSERT INTO" not in query


def test_system_pool_only_checks_pg_database(
    accessor: WorkspaceAccessor, database: FakeDatabase,
) -> None:
    accessor(user=USER_UUID).list()
    for query, _params in database.system.queries:
        assert "pg_database" in query
        assert "workspace." not in query


def test_on_load_hangs_accessor_on_state(database: FakeDatabase, log: RecordingLog) -> None:
    from modules.db.provider import DatabaseProvider
    from modules.workspace import WorkspaceModule

    class Services:
        def __init__(self) -> None:
            self._reg: dict[type, object] = {}

        def register(self, cls: type, inst: object) -> None:
            self._reg[cls] = inst

        def resolve(self, cls: type) -> object:
            if cls is DatabaseProvider:
                return database
            if cls in self._reg:
                return self._reg[cls]
            raise LookupError(getattr(cls, "__name__", cls))

    class State:
        def __init__(self) -> None:
            self.log = log
            self.services = Services()

    state = State()
    WorkspaceModule(config=WorkspaceConfig()).on_load(state)
    assert isinstance(state.workspace, WorkspaceAccessor)
    assert database.created == []
    assert database.schema_calls == []
    assert state.workspace(user=USER_UUID).list()["total"] == 0
    from modules.workspace.provider import WorkspaceProvider

    assert isinstance(state.services.resolve(WorkspaceProvider), WorkspaceProvider)
