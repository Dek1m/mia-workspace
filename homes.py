"""Unix-пользователь и листинг ~/ в контейнере бэка."""
from __future__ import annotations

import os
import pwd
import re
import subprocess
from pathlib import Path

from .fs import FsError, join_rel

__all__ = ["unix_name", "ensure_unix_home", "list_home"]

_SAFE = re.compile(r"[^a-z0-9_-]")


def unix_name(raw: str) -> str:
    name = _SAFE.sub("", raw.strip().lower())
    if not name:
        name = "user"
    if name[0].isdigit():
        name = "u" + name
    return name[:32]


def ensure_unix_home(name: str, home_root: str = "/home") -> str:
    safe = unix_name(name)
    home = Path(home_root) / safe
    try:
        pwd.getpwnam(safe)
    except KeyError:
        subprocess.run(
            ["useradd", "-m", "-d", str(home), "-s", "/usr/sbin/nologin", safe],
            check=False,
            capture_output=True,
        )
    home.mkdir(parents=True, exist_ok=True)
    try:
        info = pwd.getpwnam(safe)
        os.chown(home, info.pw_uid, info.pw_gid)
    except (KeyError, PermissionError, OSError):
        pass
    return str(home)


def list_home(home: str, rel: str = "") -> list[dict[str, str]]:
    root = Path(home).resolve()
    path = join_rel(root, rel) if rel else root
    if not path.is_dir():
        raise FsError("not a directory", "NOT_FOUND")
    items: list[dict[str, str]] = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.name.startswith(".") or child.name == "Trash":
            continue
        items.append({
            "name": child.name,
            "kind": "folder" if child.is_dir() else "file",
            "rel_path": str(child.relative_to(root)),
        })
    return items
