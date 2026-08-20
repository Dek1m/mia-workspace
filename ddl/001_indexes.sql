-- 001_indexes.sql: индексы workspaces и sessions
-- events индексируется в 002_events.sql ПОСЛЕ смены кучи на партиции
-- Идемпотентно: IF NOT EXISTS

COMMENT ON SCHEMA workspace IS
    'Домен workspace в per-user БД. Нет знаний об auth.';

COMMENT ON TABLE workspace.workspaces IS
    'Продуктовые пространства пользователя. Одна PostgreSQL-БД = один пользователь.';
COMMENT ON TABLE workspace.sessions IS
    'Сессии внутри пространства. agent_id — непрозрачный UUID, без FK на другие модули.';

-- Список пространств: активные, свежие сверху
CREATE INDEX IF NOT EXISTS idx_workspaces_updated
    ON workspace.workspaces (updated_at DESC, id DESC)
    WHERE NOT is_archived;

-- Список сессий пространства: свежие сверху
CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated
    ON workspace.sessions (workspace_id, updated_at DESC, id DESC);

-- Частый фильтр UI: только активные сессии пространства
CREATE INDEX IF NOT EXISTS idx_sessions_workspace_active
    ON workspace.sessions (workspace_id, updated_at DESC)
    WHERE status = 'active';
