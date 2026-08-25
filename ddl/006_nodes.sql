-- 006_nodes.sql: дерево папок/файлов + флаги вкладок сессии
-- Идемпотентно. Реальные пути на диске; в БД — uuid, имя, rel_path, размер.

ALTER TABLE workspace.workspaces
    ADD COLUMN IF NOT EXISTS root_path TEXT;

ALTER TABLE workspace.sessions
    ADD COLUMN IF NOT EXISTS tab_open BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE workspace.sessions
    ADD COLUMN IF NOT EXISTS agent_busy BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS workspace.nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspace.workspaces(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES workspace.nodes(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR(255) NOT NULL,
    rel_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE workspace.nodes IS
    'Папки и файлы workspace. rel_path относительно root_path. Диск — источник байт.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_ws_rel_path
    ON workspace.nodes (workspace_id, rel_path);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_ws_parent_name_root
    ON workspace.nodes (workspace_id, name)
    WHERE parent_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_ws_parent_name
    ON workspace.nodes (workspace_id, parent_id, name)
    WHERE parent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nodes_ws_parent
    ON workspace.nodes (workspace_id, parent_id, kind, name);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_nodes_kind'
          AND conrelid = 'workspace.nodes'::regclass
    ) THEN
        ALTER TABLE workspace.nodes
            ADD CONSTRAINT chk_nodes_kind
            CHECK (kind IN ('folder', 'file'));
    END IF;
END $$;
