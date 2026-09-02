"""Юнит-тесты membership-конфликтов линковки."""
from __future__ import annotations

import pytest

from modules.workspace.facade import WorkspaceError, linked_conflict, raise_linked_conflict


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
