-- 005_checks.sql: именованные CHECK, которых нет в dict-схеме
-- Идемпотентно через pg_constraint

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_workspaces_name'
          AND conrelid = 'workspace.workspaces'::regclass
    ) THEN
        ALTER TABLE workspace.workspaces
            ADD CONSTRAINT chk_workspaces_name
            CHECK (length(btrim(name)) >= 1);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_sessions_title'
          AND conrelid = 'workspace.sessions'::regclass
    ) THEN
        ALTER TABLE workspace.sessions
            ADD CONSTRAINT chk_sessions_title
            CHECK (length(btrim(title)) >= 1);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_sessions_status'
          AND conrelid = 'workspace.sessions'::regclass
    ) THEN
        ALTER TABLE workspace.sessions
            ADD CONSTRAINT chk_sessions_status
            CHECK (status IN ('active', 'archived', 'closed'));
    END IF;
END $$;

-- events: CHECK уже в 002 CREATE TABLE. Повторно — если parent
-- создан без них (ручной путь). На партиционированной таблице
-- ADD CONSTRAINT применяется к parent и всем партициям.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_events_kind'
          AND conrelid = 'workspace.events'::regclass
    ) THEN
        ALTER TABLE workspace.events
            ADD CONSTRAINT chk_events_kind
            CHECK (kind IN ('message', 'action'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_events_message_role'
          AND conrelid = 'workspace.events'::regclass
    ) THEN
        ALTER TABLE workspace.events
            ADD CONSTRAINT chk_events_message_role
            CHECK (kind <> 'message' OR role IS NOT NULL);
    END IF;
END $$;
