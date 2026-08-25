"""Диск workspace: sandbox и имена."""
from __future__ import annotations

import pytest

from modules.workspace.fs import FsError, folder_stats, mkdir, safe_name, touch


def test_safe_name_rejects_slash() -> None:
    with pytest.raises(FsError):
        safe_name("../x")
    with pytest.raises(FsError):
        safe_name("a/b")
    assert safe_name(" src ") == "src"


def test_mkdir_touch_stats(tmp_path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    folder = mkdir(root, "docs")
    file_path = touch(root, "docs/readme.md")
    file_path.write_text("hi")
    files, size = folder_stats(folder)
    assert files == 1
    assert size == 2
