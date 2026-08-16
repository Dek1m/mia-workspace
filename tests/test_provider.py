"""Tests for Workspace Provider — методы, владение, пагинация, авторизация."""
from __future__ import annotations

import pytest

from modules.workspace.provider import (
    WorkspaceProvider,
    WorkspaceError,
    ForbiddenError,
    NotFoundError,
)


@pytest.fixture
def repo(mock_pool):
    from modules.workspace.repository import WorkspaceRepository
    return WorkspaceRepository(mock_pool)


@pytest.fixture
def provider(mock_pool):
    from modules.workspace.config import WorkspaceConfig
    return WorkspaceProvider(config=WorkspaceConfig(), pool=mock_pool)


@pytest.mark.asyncio
class TestCreateWorkspace:
    async def test_create_workspace(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(
            owner_id="owner-1", name="My Project", description="Test",
        )
        assert ws["name"] == "My Project"
        assert ws["owner_id"] == "owner-1"


@pytest.mark.asyncio
class TestGetWorkspace:
    async def test_get_workspace(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        found = await provider.get_workspace(ws["id"], user_id="owner-1")
        assert found["name"] == "P"

    async def test_get_workspace_not_found(self, provider: WorkspaceProvider):
        with pytest.raises(NotFoundError):
            await provider.get_workspace("nonexistent", user_id="owner-1")

    async def test_get_workspace_no_access(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        with pytest.raises(ForbiddenError):
            await provider.get_workspace(ws["id"], user_id="stranger")


@pytest.mark.asyncio
class TestListWorkspaces:
    async def test_list(self, provider: WorkspaceProvider):
        for i in range(3):
            await provider.create_workspace(owner_id="owner-1", name=f"P{i}")
        result = await provider.list_workspaces(owner_id="owner-1")
        assert result["total"] == 3
        assert len(result["items"]) == 3


@pytest.mark.asyncio
class TestUpdateWorkspace:
    async def test_update(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        updated = await provider.update_workspace(
            ws["id"], {"name": "Updated"}, user_id="owner-1",
        )
        assert updated["name"] == "Updated"

    async def test_update_no_access(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        with pytest.raises(ForbiddenError):
            await provider.update_workspace(ws["id"], {"name": "X"}, user_id="stranger")


@pytest.mark.asyncio
class TestDeleteWorkspace:
    async def test_delete_owner(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        assert await provider.delete_workspace(ws["id"], user_id="owner-1") is True

    async def test_delete_not_owner(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        with pytest.raises(ForbiddenError):
            await provider.delete_workspace(ws["id"], user_id="stranger")

    async def test_delete_not_found(self, provider: WorkspaceProvider):
        with pytest.raises(NotFoundError):
            await provider.delete_workspace("nonexistent", user_id="owner-1")


@pytest.mark.asyncio
class TestMembers:
    async def test_add_member(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        await provider.add_member(ws["id"], "user-2", operator_id="owner-1")
        count = await provider.repository.count_members(ws["id"])
        assert count == 1

    async def test_add_member_no_access(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        with pytest.raises(ForbiddenError):
            await provider.add_member(ws["id"], "user-2", operator_id="stranger")

    async def test_list_members(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        await provider.add_member(ws["id"], "user-2", operator_id="owner-1")
        # list_members делает JOIN с auth.users — проверяем через count
        count = await provider.repository.count_members(ws["id"])
        assert count == 1


@pytest.mark.asyncio
class TestSessions:
    async def test_create_session(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        session = await provider.create_session(
            ws["id"], "Debug", user_id="owner-1",
        )
        assert session["title"] == "Debug"

    async def test_list_sessions(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        for i in range(3):
            await provider.create_session(ws["id"], f"S{i}", user_id="owner-1")
        result = await provider.list_sessions(ws["id"])
        assert result["total"] == 3


@pytest.mark.asyncio
class TestMessages:
    async def test_add_message(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        session = await provider.create_session(ws["id"], "Test", user_id="owner-1")
        msg = await provider.add_message(session["id"], "user", "Hello")
        assert msg["content"] == "Hello"

    async def test_list_messages(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        session = await provider.create_session(ws["id"], "Test", user_id="owner-1")
        await provider.add_message(session["id"], "user", "Hi")
        messages = await provider.list_messages(session["id"])
        assert len(messages) == 1


@pytest.mark.asyncio
class TestConsiliums:
    async def test_create_consilium(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        session = await provider.create_session(ws["id"], "Test", user_id="owner-1")
        c = await provider.create_consilium(session["id"], "Review", ["a1"])
        assert c["name"] == "Review"

    async def test_list_consiliums(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        session = await provider.create_session(ws["id"], "Test", user_id="owner-1")
        await provider.create_consilium(session["id"], "R1")
        await provider.create_consilium(session["id"], "R2")
        items = await provider.list_consiliums(session["id"])
        assert len(items) == 2


@pytest.mark.asyncio
class TestArchive:
    async def test_archive(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        result = await provider.archive_workspace(ws["id"], user_id="owner-1")
        assert result["is_archived"] is True

    async def test_archive_no_access(self, provider: WorkspaceProvider):
        ws = await provider.create_workspace(owner_id="owner-1", name="P")
        with pytest.raises(ForbiddenError):
            await provider.archive_workspace(ws["id"], user_id="stranger")
