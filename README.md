# workspace

Модуль управления проектами для Mia Framework.

## Features

- Workspace CRUD (создание, чтение, обновление, архивирование)
- Папки для организации сессий
- Сессии агентов с историей сообщений
- Консилиумы агентов (интеграция с LLM — Фаза 6)
- Участники workspace с ролями (owner/manager/viewer)
- Schema-first БД: PostgreSQL + DDL-индексы
- Auth-схема: workspace:create/read/update/delete/list/member_manage/session_create/session_read

## Module Structure

```
__init__.py    — ModuleBase, on_load
config.py      — WorkspaceConfig
schema.py      — AUTH_SCHEMA (permissions + roles)
schemas.py     — DB_SCHEMA (dict для register_schema)
repository.py  — WorkspaceRepository (SQL queries)
provider.py    — WorkspaceProvider (business logic + @task + @auth_method)
ddl/           — SQL-индексы (идемпотентно)
tests/         — unit-тесты (MockPool)
```

## Integration

```python
app.load_module("workspace")
provider = app.services.resolve(WorkspaceProvider)
ws = await provider.create_workspace(owner_id="u1", name="My Project")
```
