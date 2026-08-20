-- 004_triggers.sql: updated_at и денормализация «последней активности»
-- Идемпотентно через pg_trigger

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'set_updated_at'
           AND pronamespace = 'workspace'::regnamespace
    ) THEN
        CREATE FUNCTION workspace.set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
            -- Если UPDATE сам задал updated_at (touch_on_event) — не затирать.
            -- Если колонка не в SET — NEW = OLD, ставим NOW().
            IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
                NEW.updated_at := NOW();
            END IF;
            RETURN NEW;
        END;
        $fn$;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_workspaces_updated_at'
          AND tgrelid = 'workspace.workspaces'::regclass
    ) THEN
        CREATE TRIGGER trg_workspaces_updated_at
            BEFORE UPDATE ON workspace.workspaces
            FOR EACH ROW
            EXECUTE FUNCTION workspace.set_updated_at();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_sessions_updated_at'
          AND tgrelid = 'workspace.sessions'::regclass
    ) THEN
        CREATE TRIGGER trg_sessions_updated_at
            BEFORE UPDATE ON workspace.sessions
            FOR EACH ROW
            EXECUTE FUNCTION workspace.set_updated_at();
    END IF;
END $$;

-- Событие двигает updated_at сессии и пространства.
-- list_sessions / list_workspaces читают это поле — JOIN по ленте дороже.
-- events append-only, триггер только AFTER INSERT.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'touch_on_event'
           AND pronamespace = 'workspace'::regnamespace
    ) THEN
        CREATE FUNCTION workspace.touch_on_event()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
            UPDATE workspace.sessions
               SET updated_at = NEW.created_at
             WHERE id = NEW.session_id
               AND updated_at < NEW.created_at;

            UPDATE workspace.workspaces w
               SET updated_at = NEW.created_at
              FROM workspace.sessions s
             WHERE s.id = NEW.session_id
               AND w.id = s.workspace_id
               AND w.updated_at < NEW.created_at;

            RETURN NULL;
        END;
        $fn$;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_events_touch'
          AND tgrelid = 'workspace.events'::regclass
    ) THEN
        CREATE TRIGGER trg_events_touch
            AFTER INSERT ON workspace.events
            FOR EACH ROW
            EXECUTE FUNCTION workspace.touch_on_event();
    END IF;
END $$;
