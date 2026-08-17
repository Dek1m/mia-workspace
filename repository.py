"""Workspace Repository — все запросы к БД через Database Provider."""
from __future__ import annotations

from typing import Any

from argenta_logging import get_logger

log = get_logger(__name__)

__all__ = ["WorkspaceRepository"]


class WorkspaceRepository:
    """Репозиторий для CRUD workspace-таблиц."""

    def __init__(self, database: Any) -> None:
        self._database = database

    # ── Workspaces ──────────────────────────────────────

    async def create_workspace(
        self,
        owner_id: str,
        name: str,
        description: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json
        row = await self._database.fetchrow(
            "INSERT INTO workspace.workspaces (owner_id, name, description, settings) "
            "VALUES ($1, $2, $3, $4::jsonb) RETURNING *",
            owner_id,
            name,
            description,
            json.dumps(settings or {}),
        )
        return dict(row) if row else {}

    async def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "SELECT * FROM workspace.workspaces WHERE id = $1", workspace_id,
        )
        return dict(row) if row else None

    async def update_workspace(
        self, workspace_id: str, data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not data:
            return await self.get_workspace(workspace_id)

        set_parts = []
        params: list[Any] = []
        idx = 1
        for key, value in data.items():
            if key == "settings" and isinstance(value, dict):
                import json
                set_parts.append(f"{key} = ${idx}::jsonb")
                params.append(json.dumps(value))
            else:
                set_parts.append(f"{key} = ${idx}")
                params.append(value)
            idx += 1

        params.append(workspace_id)
        row = await self._database.fetchrow(
            f"UPDATE workspace.workspaces SET {', '.join(set_parts)}, "
            f"updated_at = NOW() WHERE id = ${idx} RETURNING *",
            *params,
        )
        return dict(row) if row else None

    async def delete_workspace(self, workspace_id: str) -> bool:
        result = await self._database.execute(
            "DELETE FROM workspace.workspaces WHERE id = $1", workspace_id,
        )
        return "DELETE 1" in str(result)

    async def list_workspaces(
        self,
        owner_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        if owner_id:
            total = await self._database.fetchval(
                "SELECT COUNT(*) FROM workspace.workspaces WHERE owner_id = $1",
                owner_id,
            )
            rows = await self._database.fetch(
                "SELECT * FROM workspace.workspaces WHERE owner_id = $1 "
                "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                owner_id, limit, offset,
            )
        else:
            total = await self._database.fetchval(
                "SELECT COUNT(*) FROM workspace.workspaces",
            )
            rows = await self._database.fetch(
                "SELECT * FROM workspace.workspaces ORDER BY created_at DESC "
                "LIMIT $1 OFFSET $2",
                limit, offset,
            )
        return [dict(r) for r in rows], total or 0

    async def archive_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "UPDATE workspace.workspaces SET is_archived = TRUE, updated_at = NOW() "
            "WHERE id = $1 RETURNING *",
            workspace_id,
        )
        return dict(row) if row else None

    # ── Folders ─────────────────────────────────────────

    async def create_folder(
        self,
        workspace_id: str,
        name: str,
        parent_id: str | None = None,
        position: int = 0,
    ) -> dict[str, Any]:
        row = await self._database.fetchrow(
            "INSERT INTO workspace.workspace_folders "
            "(workspace_id, name, parent_id, position) "
            "VALUES ($1, $2, $3, $4) RETURNING *",
            workspace_id, name, parent_id, position,
        )
        return dict(row) if row else {}

    async def get_folder(self, folder_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "SELECT * FROM workspace.workspace_folders WHERE id = $1", folder_id,
        )
        return dict(row) if row else None

    async def update_folder(
        self, folder_id: str, data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not data:
            return await self.get_folder(folder_id)

        set_parts = []
        params: list[Any] = []
        idx = 1
        for key, value in data.items():
            set_parts.append(f"{key} = ${idx}")
            params.append(value)
            idx += 1

        params.append(folder_id)
        row = await self._database.fetchrow(
            f"UPDATE workspace.workspace_folders SET {', '.join(set_parts)} "
            f"WHERE id = ${idx} RETURNING *",
            *params,
        )
        return dict(row) if row else None

    async def delete_folder(self, folder_id: str) -> bool:
        result = await self._database.execute(
            "DELETE FROM workspace.workspace_folders WHERE id = $1", folder_id,
        )
        return "DELETE 1" in str(result)

    async def list_folders(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = await self._database.fetch(
            "SELECT * FROM workspace.workspace_folders "
            "WHERE workspace_id = $1 ORDER BY position",
            workspace_id,
        )
        return [dict(r) for r in rows]

    # ── Sessions ────────────────────────────────────────

    async def create_session(
        self,
        workspace_id: str,
        title: str,
        folder_id: str | None = None,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json
        row = await self._database.fetchrow(
            "INSERT INTO workspace.sessions "
            "(workspace_id, title, folder_id, agent_id, metadata, status) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, 'active') RETURNING *",
            workspace_id, title, folder_id, agent_id,
            json.dumps(metadata or {}),
        )
        return dict(row) if row else {}

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "SELECT * FROM workspace.sessions WHERE id = $1", session_id,
        )
        return dict(row) if row else None

    async def update_session(
        self, session_id: str, data: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not data:
            return await self.get_session(session_id)

        set_parts = []
        params: list[Any] = []
        idx = 1
        for key, value in data.items():
            if key == "metadata" and isinstance(value, dict):
                import json
                set_parts.append(f"{key} = ${idx}::jsonb")
                params.append(json.dumps(value))
            else:
                set_parts.append(f"{key} = ${idx}")
                params.append(value)
            idx += 1

        params.append(session_id)
        row = await self._database.fetchrow(
            f"UPDATE workspace.sessions SET {', '.join(set_parts)}, "
            f"updated_at = NOW() WHERE id = ${idx} RETURNING *",
            *params,
        )
        return dict(row) if row else None

    async def delete_session(self, session_id: str) -> bool:
        result = await self._database.execute(
            "DELETE FROM workspace.sessions WHERE id = $1", session_id,
        )
        return "DELETE 1" in str(result)

    async def list_sessions(
        self,
        workspace_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        total = await self._database.fetchval(
            "SELECT COUNT(*) FROM workspace.sessions WHERE workspace_id = $1",
            workspace_id,
        )
        rows = await self._database.fetch(
            "SELECT * FROM workspace.sessions WHERE workspace_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            workspace_id, limit, offset,
        )
        return [dict(r) for r in rows], total or 0

    async def archive_session(self, session_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "UPDATE workspace.sessions SET status = 'archived', updated_at = NOW() "
            "WHERE id = $1 RETURNING *",
            session_id,
        )
        return dict(row) if row else None

    # ── Messages ────────────────────────────────────────

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import json
        row = await self._database.fetchrow(
            "INSERT INTO workspace.session_messages "
            "(session_id, role, content, agent_id, metadata) "
            "VALUES ($1, $2, $3, $4, $5::jsonb) RETURNING *",
            session_id, role, content, agent_id,
            json.dumps(metadata or {}),
        )
        return dict(row) if row else {}

    async def list_messages(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = await self._database.fetch(
            "SELECT * FROM workspace.session_messages "
            "WHERE session_id = $1 ORDER BY created_at ASC "
            "LIMIT $2 OFFSET $3",
            session_id, limit, offset,
        )
        return [dict(r) for r in rows]

    # ── Consiliums ──────────────────────────────────────

    async def create_consilium(
        self,
        session_id: str,
        name: str,
        agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        import json
        row = await self._database.fetchrow(
            "INSERT INTO workspace.agent_consiliums "
            "(session_id, name, agent_ids, status) "
            "VALUES ($1, $2, $3::jsonb, 'pending') RETURNING *",
            session_id, name, json.dumps(agent_ids or []),
        )
        return dict(row) if row else {}

    async def get_consilium(self, consilium_id: str) -> dict[str, Any] | None:
        row = await self._database.fetchrow(
            "SELECT * FROM workspace.agent_consiliums WHERE id = $1", consilium_id,
        )
        return dict(row) if row else None

    async def update_consilium_status(
        self,
        consilium_id: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        import json
        params: list[Any] = [status]
        idx = 2
        result_json = json.dumps(result) if result else None
        params.append(result_json)
        params.append(consilium_id)

        row = await self._database.fetchrow(
            f"UPDATE workspace.agent_consiliums "
            f"SET status = ${1}, result = ${idx - 1}::jsonb, updated_at = NOW() "
            f"WHERE id = ${idx} RETURNING *",
            *params,
        )
        return dict(row) if row else None

    async def list_consiliums(self, session_id: str) -> list[dict[str, Any]]:
        rows = await self._database.fetch(
            "SELECT * FROM workspace.agent_consiliums "
            "WHERE session_id = $1 ORDER BY created_at",
            session_id,
        )
        return [dict(r) for r in rows]

    # ── Members ─────────────────────────────────────────

    async def add_member(
        self,
        workspace_id: str,
        user_id: str,
        role: str = "viewer",
    ) -> None:
        await self._database.execute(
            "INSERT INTO workspace.workspace_members (workspace_id, user_id, role) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            workspace_id, user_id, role,
        )

    async def remove_member(self, workspace_id: str, user_id: str) -> bool:
        result = await self._database.execute(
            "DELETE FROM workspace.workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            workspace_id, user_id,
        )
        return "DELETE 1" in str(result)

    async def list_members(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = await self._database.fetch(
            "SELECT wm.*, u.username, u.email "
            "FROM workspace.workspace_members wm "
            "JOIN auth.users u ON u.id = wm.user_id "
            "WHERE wm.workspace_id = $1",
            workspace_id,
        )
        return [dict(r) for r in rows]

    async def get_member_role(self, workspace_id: str, user_id: str) -> str | None:
        row = await self._database.fetchrow(
            "SELECT role FROM workspace.workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            workspace_id, user_id,
        )
        return row["role"] if row else None

    async def count_members(self, workspace_id: str) -> int:
        result = await self._database.fetchval(
            "SELECT COUNT(*) FROM workspace.workspace_members WHERE workspace_id = $1",
            workspace_id,
        )
        return result or 0

    # ── Access check ────────────────────────────────────

    async def user_can_access(self, workspace_id: str, user_id: str) -> bool:
        """Проверить доступ: owner или member."""
        row = await self._database.fetchrow(
            "SELECT 1 FROM workspace.workspaces WHERE id = $1 AND owner_id = $2",
            workspace_id, user_id,
        )
        if row:
            return True

        row = await self._database.fetchrow(
            "SELECT 1 FROM workspace.workspace_members "
            "WHERE workspace_id = $1 AND user_id = $2",
            workspace_id, user_id,
        )
        return row is not None
