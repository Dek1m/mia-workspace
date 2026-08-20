# workspace

Per-user PostgreSQL database + продуктовые пространства внутри неё.

## API

```python
app.load_module("workspace")

state.workspace(user=uuid | User, ws=uuid)          # → Workspace
state.workspace(user=...).list()                    # JSON список пространств
state.workspace(user=..., ws=...).sessions()        # JSON сессии
state.workspace(user=..., ws=...).sessions(sid)     # JSON лента events
```

`user` можно передать как `state.auth.user('uuid')`. Одна PostgreSQL database на пользователя (`belle_workspace_{uuid_hex}`). Продуктовый workspace — строка в `workspace.workspaces`, не `CREATE DATABASE`.

SQL снаружи — только функции `workspace.*` из `ddl/003_functions.sql`.
