"""Реальные папки/файлы workspace. Путь только внутри root."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

__all__ = [
    "FsError",
    "safe_name",
    "workspace_dir",
    "ensure_dir",
    "join_rel",
    "mkdir",
    "touch",
    "remove",
    "folder_stats",
]

_NAME = re.compile(r"^[^/\\]{1,255}$")


class FsError(Exception):
    def __init__(self, message: str, code: str = "FS_ERROR") -> None:
        self.code = code
        super().__init__(message)


def safe_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or not _NAME.match(value) or ".." in value:
        raise FsError("invalid name", "INVALID_NAME")
    return value


def workspace_dir(fs_root: str, user_hex: str, workspace_id: str) -> Path:
    root = Path(fs_root).resolve()
    path = (root / user_hex / workspace_id.replace("-", "")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise FsError("path escape", "PATH_ESCAPE") from exc
    return path


def ensure_dir(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def join_rel(root: Path, rel: str) -> Path:
    target = (root / rel).resolve() if rel else root.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FsError("path escape", "PATH_ESCAPE") from exc
    return target


def mkdir(root: Path, rel: str) -> Path:
    path = join_rel(root, rel)
    path.mkdir(parents=True, exist_ok=True)
    return path


def touch(root: Path, rel: str) -> Path:
    path = join_rel(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


def remove(root: Path, rel: str) -> None:
    path = join_rel(root, rel)
    if path.is_dir():
        shutil.rmtree(path)
        return
    if path.exists():
        path.unlink()


def folder_stats(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    if not path.is_dir():
        return 0, 0
    for dirpath, _dirnames, filenames in os.walk(path):
        files += len(filenames)
        for name in filenames:
            try:
                size += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return files, size
