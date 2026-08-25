"""Юнит-тесты unix-имени и листинга ~/."""
from __future__ import annotations

from pathlib import Path

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
