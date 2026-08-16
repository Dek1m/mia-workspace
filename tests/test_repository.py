"""Tests for Workspace Repository — CRUD, связи, пагинация, каскад."""
from __future__ import annotations

import pytest

from modules.workspace.repository import WorkspaceRepository


@pytest.fixture
def repo(mock_pool) -> WorkspaceRepository:
    return WorkspaceRepository(mock_pool)


@pytest.mark.asyncio
class TestWorkspaceCRUD:
    async def test_create_workspace(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project", "Description")
        assert ws["name"] == "My Project"
        assert ws["owner_id"] == "owner-1"
        assert "id" in ws

    async def test_get_workspace(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        found = await repo.get_workspace(ws["id"])
        assert found is not None
        assert found["name"] == "My Project"

    async def test_get_workspace_not_found(self, repo: WorkspaceRepository):
        found = await repo.get_workspace("nonexistent")
        assert found is None

    async def test_update_workspace(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        updated = await repo.update_workspace(ws["id"], {"name": "Renamed"})
        assert updated is not None
        assert updated["name"] == "Renamed"

    async def test_delete_workspace(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        assert await repo.delete_workspace(ws["id"]) is True
        assert await repo.get_workspace(ws["id"]) is None

    async def test_archive_workspace(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        archived = await repo.archive_workspace(ws["id"])
        assert archived is not None
        assert archived["is_archived"] is True

    async def test_list_workspaces(self, repo: WorkspaceRepository):
        for i in range(5):
            await repo.create_workspace(f"owner-{i}", f"Project {i}")
        items, total = await repo.list_workspaces(owner_id="owner-1")
        assert total == 1
        assert len(items) == 1

    async def test_list_workspaces_pagination(self, repo: WorkspaceRepository):
        for i in range(5):
            await repo.create_workspace("owner-1", f"Project {i}")
        items, total = await repo.list_workspaces(owner_id="owner-1", offset=0, limit=2)
        assert len(items) == 2
        assert total == 5


@pytest.mark.asyncio
class TestFolderCRUD:
    async def test_create_folder(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        folder = await repo.create_folder(ws["id"], "Subfolder")
        assert folder["name"] == "Subfolder"
        assert folder["workspace_id"] == ws["id"]

    async def test_list_folders(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        await repo.create_folder(ws["id"], "Folder A", position=1)
        await repo.create_folder(ws["id"], "Folder B", position=0)
        folders = await repo.list_folders(ws["id"])
        assert len(folders) == 2

    async def test_delete_folder(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        folder = await repo.create_folder(ws["id"], "To Delete")
        assert await repo.delete_folder(folder["id"]) is True


@pytest.mark.asyncio
class TestSessionCRUD:
    async def test_create_session(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "Debug Session")
        assert session["title"] == "Debug Session"
        assert session["workspace_id"] == ws["id"]
        assert session["status"] == "active"

    async def test_list_sessions(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        for i in range(3):
            await repo.create_session(ws["id"], f"Session {i}")
        items, total = await repo.list_sessions(ws["id"])
        assert total == 3
        assert len(items) == 3

    async def test_archive_session(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "To Archive")
        archived = await repo.archive_session(session["id"])
        assert archived is not None
        assert archived["status"] == "archived"


@pytest.mark.asyncio
class TestMessageCRUD:
    async def test_add_message(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "Test")
        msg = await repo.add_message(session["id"], "user", "Hello world")
        assert msg["role"] == "user"
        assert msg["content"] == "Hello world"

    async def test_list_messages(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "Test")
        await repo.add_message(session["id"], "user", "Hello")
        await repo.add_message(session["id"], "assistant", "Hi there")
        messages = await repo.list_messages(session["id"])
        assert len(messages) == 2


@pytest.mark.asyncio
class TestConsiliumCRUD:
    async def test_create_consilium(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "Test")
        consilium = await repo.create_consilium(
            session["id"], "Agent Review", ["agent-1", "agent-2"],
        )
        assert consilium["name"] == "Agent Review"
        assert consilium["status"] == "pending"

    async def test_list_consiliums(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        session = await repo.create_session(ws["id"], "Test")
        await repo.create_consilium(session["id"], "Review 1")
        await repo.create_consilium(session["id"], "Review 2")
        items = await repo.list_consiliums(session["id"])
        assert len(items) == 2


@pytest.mark.asyncio
class TestMemberCRUD:
    async def test_add_member(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        await repo.add_member(ws["id"], "user-2", "viewer")
        members = await repo.list_members(ws["id"])
        assert len(members) == 1

    async def test_remove_member(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        await repo.add_member(ws["id"], "user-2")
        assert await repo.remove_member(ws["id"], "user-2") is True
        members = await repo.list_members(ws["id"])
        assert len(members) == 0

    async def test_user_can_access_owner(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        assert await repo.user_can_access(ws["id"], "owner-1") is True

    async def test_user_can_access_member(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        await repo.add_member(ws["id"], "user-2")
        assert await repo.user_can_access(ws["id"], "user-2") is True

    async def test_user_cannot_access(self, repo: WorkspaceRepository):
        ws = await repo.create_workspace("owner-1", "My Project")
        assert await repo.user_can_access(ws["id"], "user-999") is False
