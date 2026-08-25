"""Юнит-тесты unix-имени и листинга ~/."""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.workspace.facade import WorkspaceError, linked_conflict, raise_linked_conflict
from modules.workspace.homes import list_home, unix_name


def test_unix_name_sanitizes() -> None:
    assert unix_name("Admin") == "admin"
    assert unix_name("12bad") == "u12bad"
    assert unix_name("weird name!") == "weirdname"


def test_list_home_tree(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("x")
    (tmp_path / ".hidden").mkdir()
    items = list_home(str(tmp_path), "")
    names = {item["name"] for item in items}
    assert "docs" in names
    assert ".hidden" not in names
    nested = list_home(str(tmp_path), "docs")
    assert nested[0]["rel_path"] == "docs/a.txt"
    assert nested[0]["kind"] == "file"


def test_linked_conflict_both_directions() -> None:
    assert linked_conflict("ret", {"ret"}) == ("ALREADY_LINKED", "ret")
    assert linked_conflict("ret/557", {"ret"}) == ("ALREADY_NESTED", "ret")
    assert linked_conflict("ret", {"ret/557/fsdf"}) == ("CONTAINS_LINKED", "ret/557/fsdf")
    assert linked_conflict("docs", {"ret"}) is None


def test_raise_linked_conflict_codes() -> None:
    with pytest.raises(WorkspaceError) as nested:
        raise_linked_conflict("a/b", {"a"})
    assert nested.value.code == "ALREADY_NESTED"
    with pytest.raises(WorkspaceError) as parent:
        raise_linked_conflict("a", {"a/b"})
    assert parent.value.code == "CONTAINS_LINKED"
