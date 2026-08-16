-- Workspace DDL: индексы для производительности
-- Идемпотентно через IF NOT EXISTS

CREATE INDEX IF NOT EXISTS idx_workspaces_owner
    ON workspace.workspaces (owner_id);

CREATE INDEX IF NOT EXISTS idx_workspace_folders_workspace
    ON workspace.workspace_folders (workspace_id);

CREATE INDEX IF NOT EXISTS idx_sessions_workspace
    ON workspace.sessions (workspace_id);

CREATE INDEX IF NOT EXISTS idx_session_messages_session
    ON workspace.session_messages (session_id);

CREATE INDEX IF NOT EXISTS idx_agent_consiliums_session
    ON workspace.agent_consiliums (session_id);
