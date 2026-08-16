"""Tests for Workspace Schema — AUTH_SCHEMA валидность, DB_SCHEMA."""
from __future__ import annotations

import pytest

from modules.workspace.schema import WORKSPACE_SCHEMA
from modules.workspace.schemas import DB_SCHEMA


class TestAuthSchema:
    """Проверка что AUTH_SCHEMA валиден."""

    def test_has_permissions(self):
        assert "permissions" in WORKSPACE_SCHEMA
        assert len(WORKSPACE_SCHEMA["permissions"]) == 8

    def test_has_roles(self):
        assert "roles" in WORKSPACE_SCHEMA
        assert len(WORKSPACE_SCHEMA["roles"]) == 2

    def test_all_permissions_have_description(self):
        for perm in WORKSPACE_SCHEMA["permissions"]:
            assert "name" in perm
            assert "description" in perm
            assert perm["description"], f"Empty description for {perm['name']}"

    def test_all_roles_have_description(self):
        for role in WORKSPACE_SCHEMA["roles"]:
            assert "name" in role
            assert "description" in role
            assert role["description"], f"Empty description for {role['name']}"

    def test_permissions_use_namespace(self):
        for perm in WORKSPACE_SCHEMA["permissions"]:
            assert perm["name"].startswith("workspace:"), (
                f"Permission '{perm['name']}' must start with 'workspace:'"
            )

    def test_roles_reference_valid_permissions(self):
        perm_names = {p["name"] for p in WORKSPACE_SCHEMA["permissions"]}
        perm_names.add("*:*")  # Wildcard

        for role in WORKSPACE_SCHEMA["roles"]:
            for perm_name in role["permissions"]:
                if perm_name == "*:*":
                    continue
                if ":" in perm_name:
                    resource, action = perm_name.split(":", 1)
                    if action == "*":
                        # resource:* — проверяем что хотя бы одна permission ресурса есть
                        has_resource = any(
                            p.startswith(f"{resource}:") for p in perm_names
                        )
                        assert has_resource, (
                            f"Role '{role['name']}' references '{perm_name}' "
                            f"but no permissions found for resource '{resource}'"
                        )
                    else:
                        assert perm_name in perm_names, (
                            f"Role '{role['name']}' references unknown permission '{perm_name}'"
                        )


class TestDBSchema:
    """Проверка DB_SCHEMA."""

    def test_has_schema_key(self):
        assert "schema" in DB_SCHEMA
        assert DB_SCHEMA["schema"] == "workspace"

    def test_has_all_tables(self):
        expected_tables = [
            "workspaces", "workspace_folders", "sessions",
            "session_messages", "agent_consiliums", "workspace_members",
        ]
        for table in expected_tables:
            assert table in DB_SCHEMA, f"Missing table: {table}"

    def test_all_tables_have_columns(self):
        for table_name, schema in DB_SCHEMA.items():
            if table_name == "schema":
                continue
            assert "columns" in schema, f"Table {table_name} missing 'columns'"
            assert len(schema["columns"]) > 0, f"Table {table_name} has no columns"

    def test_workspace_members_composite_pk(self):
        """workspace_members имеет составной PK."""
        wm = DB_SCHEMA["workspace_members"]
        assert wm.get("auto_id") is False
        assert wm.get("primary_key") == ["workspace_id", "user_id"]
