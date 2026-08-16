"""Workspace Tests — конфигурация и фикстуры (MockPool)."""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# ── Динамическая загрузка модулей с дефисом ──────────────

_WORKSPACE_DIR = Path(__file__).resolve().parent.parent

# Регистрируем фейковый пакет modules.workspace
if "modules.workspace" not in sys.modules:
    _fake_pkg = types.ModuleType("modules.workspace")
    _fake_pkg.__path__ = [str(_WORKSPACE_DIR)]
    _fake_pkg.__package__ = "modules.workspace"
    sys.modules["modules.workspace"] = _fake_pkg

    for submod in ["config", "schema", "schemas", "repository", "provider"]:
        file_path = _WORKSPACE_DIR / f"{submod}.py"
        if file_path.exists():
            spec = importlib.util.spec_from_file_location(
                f"modules.workspace.{submod}", file_path,
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                mod.__package__ = "modules.workspace"
                sys.modules[f"modules.workspace.{submod}"] = mod
                spec.loader.exec_module(mod)
                setattr(_fake_pkg, submod, mod)

    # Загружаем __init__.py
    init_file = _WORKSPACE_DIR / "__init__.py"
    if init_file.exists():
        code = compile(init_file.read_bytes(), str(init_file), "exec")
        exec(code, _fake_pkg.__dict__)


# ── Mock Pool ────────────────────────────────────────────


class MockRow:
    """Мок строки результата запроса."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def keys(self):
        return self._data.keys()

    def __iter__(self):
        return iter(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def dict(self):
        return dict(self._data)


class MockPool:
    """Мок asyncpg pool для unit-тестов workspace."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {
            "workspace.workspaces": {},
            "workspace.workspace_folders": {},
            "workspace.sessions": {},
            "workspace.session_messages": {},
            "workspace.agent_consiliums": {},
            "workspace.workspace_members": {},
            "auth.users": {},  # Для JOIN запросов
        }
        self._seq: int = 0

    def _next_id(self) -> str:
        self._seq += 1
        return str(uuid.uuid4())

    def _find_table(self, query: str) -> str | None:
        q = query.lower()
        for table in self._data:
            if table in q:
                return table
        return None

    async def execute(self, query: str, *params: Any) -> str:
        q = query.lower().strip()
        if "insert into" in q:
            return self._do_insert(query, params)
        if "update " in q and " set " in q:
            return self._do_update(query, params)
        if "delete from" in q:
            return self._do_delete(query, params)
        return "OK"

    async def fetchval(self, query: str, *params: Any) -> Any:
        if "count(*)" in query.lower():
            rows = await self.fetch(query, *params)
            if rows:
                return rows[0]["count"] if isinstance(rows[0], MockRow) else rows[0]
            return 0
        row = await self.fetchrow(query, *params)
        if row is None:
            return None
        keys = list(row.keys())
        return row[keys[0]] if keys else None

    async def fetchrow(self, query: str, *params: Any) -> MockRow | None:
        q = query.lower().strip()
        if "insert into" in q and "returning" in q:
            table = self._find_table(query)
            if not table:
                return None
            self._do_insert(query, params)
            if table in self._data and self._data[table]:
                last_id = list(self._data[table].keys())[-1]
                return MockRow(self._data[table][last_id])
            return None
        if "update " in q and "returning" in q:
            table = self._find_table(query)
            if not table:
                return None
            updated_rows = self._do_update_returning(query, params)
            return MockRow(updated_rows[0]) if updated_rows else None
        rows = await self.fetch(query, *params)
        return rows[0] if rows else None

    async def fetch(self, query: str, *params: Any) -> list[MockRow]:
        q = query.lower().strip()

        # UNION — разбиваем и объединяем
        if " union " in q:
            return await self._handle_union(query, params)

        table = self._find_table(query)
        if not table:
            return []

        all_rows = list(self._data[table].values())

        if "count(*)" in q and "where" not in q:
            return [MockRow({"count": len(all_rows)})]

        if "where" in q:
            where_idx = q.index("where")
            where_part = q[where_idx + 5:]
            for keyword in ("order by", "limit", "offset", "group by"):
                if keyword in where_part:
                    where_part = where_part.split(keyword)[0]

            conditions = self._extract_conditions(where_part, params)
            all_rows = [r for r in all_rows if self._match(r, conditions)]

        if "count(*)" in q:
            return [MockRow({"count": len(all_rows)})]

        if "order by" in q:
            desc = "desc" in q
            all_rows.sort(key=lambda r: r.get("created_at", ""), reverse=desc)

        m = re.search(r'limit\s+\$?\d+', q)
        if m:
            limit_str = m.group(0).split()[-1]
            if limit_str.startswith("$"):
                idx = int(limit_str[1:]) - 1
                if idx < len(params):
                    all_rows = all_rows[:params[idx]]
            else:
                all_rows = all_rows[:int(limit_str)]

        m = re.search(r'offset\s+\$?\d+', q)
        if m:
            offset_str = m.group(0).split()[-1]
            if offset_str.startswith("$"):
                idx = int(offset_str[1:]) - 1
                if idx < len(params):
                    all_rows = all_rows[params[idx]:]

        return [MockRow(r) for r in all_rows]

    async def _handle_union(self, query: str, params: tuple) -> list[MockRow]:
        """Обработка UNION запросов."""
        parts = re.split(r'\bunion\b', query, flags=re.IGNORECASE)
        all_results = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            rows = await self.fetch(part, *params)
            all_results.extend(rows)

        seen_ids = set()
        unique = []
        for row in all_results:
            row_dict = row._data if isinstance(row, MockRow) else row
            row_id = row_dict.get("id", str(row_dict))
            if row_id not in seen_ids:
                seen_ids.add(row_id)
                unique.append(row)

        return unique

    def _extract_conditions(self, where_part: str, params: tuple) -> list[tuple[str, Any]]:
        conditions = []
        for match in re.finditer(r'(\w+)\s*(?:=|ilike)\s*\$(\d+)', where_part):
            field = match.group(1)
            param_idx = int(match.group(2)) - 1
            if 0 <= param_idx < len(params):
                conditions.append((field, params[param_idx]))
        return conditions

    def _match(self, row: dict, conditions: list) -> bool:
        for field, value in conditions:
            row_val = row.get(field)
            if isinstance(value, (list, tuple)):
                if row_val not in value:
                    return False
            else:
                if row_val != value:
                    if isinstance(value, str) and isinstance(row_val, str):
                        if value.startswith("%") and value.endswith("%"):
                            search = value[1:-1]
                            if search.lower() not in row_val.lower():
                                return False
                        elif row_val is None and value is not None:
                            return False
                        elif row_val is not None and value is None:
                            return False
                        else:
                            return False
                    elif row_val is None and value is not None:
                        return False
                    elif row_val is not None and value is None:
                        return False
                    else:
                        return False
        return True

    def _do_insert(self, query: str, params: tuple) -> str:
        m = re.search(r'insert\s+into\s+(\S+)\s*\(([^)]+)\)', query.lower())
        if not m:
            return "INSERT 0 1"

        table = m.group(1)
        cols_str = m.group(2)
        columns = [c.strip() for c in cols_str.split(",")]

        if table not in self._data:
            self._data[table] = {}

        row_id = self._next_id()
        row: dict[str, Any] = {"id": row_id}

        for i, col in enumerate(columns):
            if col == "id":
                continue
            if i < len(params):
                row[col] = params[i]

        # Обработка строковых литералов в VALUES: VALUES ($1, 'active')
        values_match = re.search(r'values\s*\((.+?)\)\s*(?:returning|$)', query, re.IGNORECASE)
        if values_match:
            values_str = values_match.group(1)
            for literal_match in re.finditer(r"'([^']+)'", values_str):
                # Определяем индекс этого значения
                literal_pos = literal_match.start()
                # Считаем запятые до этой позиции чтобы найти колонку
                commas_before = values_str[:literal_pos].count(',')
                if commas_before < len(columns):
                    col = columns[commas_before]
                    if col not in row or row[col] is None:
                        row[col] = literal_match.group(1)

        if "on conflict" in query.lower():
            # ON CONFLICT DO NOTHING — просто вставляем (в моке нет реальных конфликтов)
            self._data[table][row_id] = row
            return "INSERT 0 1"

        self._data[table][row_id] = row
        return "INSERT 0 1"

    def _do_update(self, query: str, params: tuple) -> str:
        table = self._find_table(query)
        if not table or table not in self._data:
            return "UPDATE 0"

        q_lower = query.lower()
        if "where" in q_lower:
            where_part = query[q_lower.index("where") + 5:]
            conditions = self._extract_conditions(where_part, params)
        else:
            conditions = []

        set_match = re.search(r'set\s+(.*?)\s+where', query.lower(), re.DOTALL)
        if not set_match:
            set_match = re.search(r'set\s+(.*?)$', query.lower(), re.DOTALL)
        if not set_match:
            return "UPDATE 0"

        set_part = set_match.group(1)
        updated = 0
        for _, row in self._data[table].items():
            if self._match(row, conditions):
                self._apply_set(row, set_part, params)
                updated += 1

        return f"UPDATE {updated}"

    def _do_update_returning(self, query: str, params: tuple) -> list[dict]:
        table = self._find_table(query)
        if not table or table not in self._data:
            return []

        q_lower = query.lower()
        if "where" in q_lower:
            where_part = query[q_lower.index("where") + 5:]
            conditions = self._extract_conditions(where_part, params)
        else:
            conditions = []

        set_match = re.search(r'set\s+(.*?)\s+where', query.lower(), re.DOTALL)
        if not set_match:
            set_match = re.search(r'set\s+(.*?)$', query.lower(), re.DOTALL)
        if not set_match:
            return []

        set_part = set_match.group(1)

        updated_rows = []
        for _, row in self._data[table].items():
            if self._match(row, conditions):
                self._apply_set(row, set_part, params)
                updated_rows.append(dict(row))

        return updated_rows

    def _apply_set(self, row: dict, set_part: str, params: tuple) -> None:
        # field = $N
        for match in re.finditer(r'(\w+)\s*=\s*\$(\d+)', set_part):
            field = match.group(1)
            param_idx = int(match.group(2)) - 1
            if 0 <= param_idx < len(params):
                row[field] = params[param_idx]

        # field = field + $N (increment)
        for match in re.finditer(r'(\w+)\s*=\s*(\w+)\s*\+\s*(?:\$(\d+)|(\d+))', set_part):
            field = match.group(1)
            if match.group(3):
                param_idx = int(match.group(3)) - 1
                increment = params[param_idx] if 0 <= param_idx < len(params) else 0
            elif match.group(4):
                increment = int(match.group(4))
            else:
                increment = 0
            current = row.get(field, 0) or 0
            row[field] = current + increment

        # field = N (literal number assignment)
        for match in re.finditer(r'(\w+)\s*=\s*(\d+)(?!\s*\+)', set_part):
            field = match.group(1)
            row[field] = int(match.group(2))

        # field = 'string_literal'
        for match in re.finditer(r"(\w+)\s*=\s*'([^']+)'", set_part):
            field = match.group(1)
            row[field] = match.group(2)

        # field = NOW() / field = NULL / field = TRUE / field = FALSE
        for match in re.finditer(r'(\w+)\s*=\s*(now\(\)|null|true|false)', set_part):
            field = match.group(1)
            value_str = match.group(2).lower()
            if value_str == "now()":
                row[field] = datetime.now(timezone.utc)
            elif value_str == "null":
                row[field] = None
            elif value_str == "true":
                row[field] = True
            elif value_str == "false":
                row[field] = False

    def _do_delete(self, query: str, params: tuple) -> str:
        table = self._find_table(query)
        if not table or table not in self._data:
            return "DELETE 0"

        q_lower = query.lower()
        if "where" in q_lower:
            where_part = query[q_lower.index("where") + 5:]
            conditions = self._extract_conditions(where_part, params)
        else:
            conditions = []
        to_delete = [
            row_id for row_id, row in self._data[table].items()
            if self._match(row, conditions)
        ]

        for row_id in to_delete:
            del self._data[table][row_id]

        return f"DELETE {len(to_delete)}"

    def insert_direct(self, table: str, row: dict[str, Any]) -> None:
        if "id" not in row:
            row["id"] = self._next_id()
        if table not in self._data:
            self._data[table] = {}
        self._data[table][row["id"]] = row

    def get_all(self, table: str) -> dict[str, dict]:
        return self._data.get(table, {})

    def clear(self) -> None:
        for table in self._data:
            self._data[table].clear()
        self._seq = 0


@pytest.fixture
def mock_pool() -> MockPool:
    return MockPool()
