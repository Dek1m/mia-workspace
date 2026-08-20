"""Tests for Workspace Schema — AUTH_SCHEMA, DB_SCHEMA, без FK на auth."""
from __future__ import annotations

from modules.workspace.schema import WORKSPACE_SCHEMA
from modules.workspace.schemas import DB_NAME_PREFIX, DB_SCHEMA, TEMPLATE_DATABASE


class TestAuthSchema:
    """Проверка что AUTH_SCHEMA валиден."""

    def test_has_permissions(self) -> None:
        assert "permissions" in WORKSPACE_SCHEMA
        assert len(WORKSPACE_SCHEMA["permissions"]) == 8

    def test_has_roles(self) -> None:
        assert "roles" in WORKSPACE_SCHEMA
        assert len(WORKSPACE_SCHEMA["roles"]) == 2

    def test_all_permissions_have_description(self) -> None:
        for perm in WORKSPACE_SCHEMA["permissions"]:
            assert "name" in perm
            assert "description" in perm
            assert perm["description"], f"Empty description for {perm['name']}"

    def test_all_roles_have_description(self) -> None:
        for role in WORKSPACE_SCHEMA["roles"]:
            assert "name" in role
            assert "description" in role
            assert role["description"], f"Empty description for {role['name']}"

    def test_permissions_use_namespace(self) -> None:
        for perm in WORKSPACE_SCHEMA["permissions"]:
            assert perm["name"].startswith("workspace:"), (
                f"Permission '{perm['name']}' must start with 'workspace:'"
            )

    def test_roles_reference_valid_permissions(self) -> None:
        perm_names = {p["name"] for p in WORKSPACE_SCHEMA["permissions"]}
        for role in WORKSPACE_SCHEMA["roles"]:
            for perm_name in role["permissions"]:
                if perm_name == "*:*":
                    continue
                if ":" in perm_name:
                    resource, action = perm_name.split(":", 1)
                    if action == "*":
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
    """Проверка DB_SCHEMA user-БД: workspaces / sessions / events."""

    def test_has_schema_key(self) -> None:
        assert "schema" in DB_SCHEMA
        assert DB_SCHEMA["schema"] == "workspace"

    def test_name_prefix_and_template(self) -> None:
        assert DB_NAME_PREFIX == "belle_workspace_"
        assert TEMPLATE_DATABASE == "template_workspace"

    def test_has_all_tables(self) -> None:
        for table in ("workspaces", "sessions", "events"):
            assert table in DB_SCHEMA, f"Missing table: {table}"

    def test_no_legacy_tables(self) -> None:
        for table in (
            "workspace_folders", "session_messages",
            "agent_consiliums", "workspace_members",
        ):
            assert table not in DB_SCHEMA

    def test_all_tables_have_columns(self) -> None:
        for table_name, schema in DB_SCHEMA.items():
            if table_name == "schema":
                continue
            assert "columns" in schema, f"Table {table_name} missing 'columns'"
            assert len(schema["columns"]) > 0, f"Table {table_name} has no columns"

    def test_events_composite_pk(self) -> None:
        events = DB_SCHEMA["events"]
        assert events.get("auto_id") is False
        assert events.get("primary_key") == ["id", "created_at"]

    def test_no_auth_references(self) -> None:
        blob = str(DB_SCHEMA)
        assert "auth.users" not in blob
        assert "REFERENCES auth" not in blob
        assert "owner_id" not in DB_SCHEMA["workspaces"]["columns"]
