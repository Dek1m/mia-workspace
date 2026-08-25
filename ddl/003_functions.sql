-- 003_functions.sql: SQL API модуля workspace
-- Python снаружи ходит только сюда (класс Workspace — фасад, не SQL).
--
-- Контракт:
--   list_workspaces / get_workspace / create_workspace
--   list_sessions   / get_session   / create_session
--   fetch_timeline  / insert_event
--
-- Лимиты зажаты (max 500), чтобы случайный LIMIT не убил user-БД.

-- ── workspaces ───────────────────────────────────────────

CREATE OR REPLACE FUNCTION workspace.create_workspace(
    p_name TEXT,
    p_description TEXT DEFAULT NULL,
    p_settings JSONB DEFAULT '{}'::jsonb
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.workspaces%ROWTYPE;
BEGIN
    IF p_name IS NULL OR btrim(p_name) = '' THEN
        RAISE EXCEPTION 'workspace name is empty'
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO workspace.workspaces (name, description, settings)
    VALUES (
        left(btrim(p_name), 255),
        p_description,
        COALESCE(p_settings, '{}'::jsonb)
    )
    RETURNING * INTO v_row;

    RETURN to_jsonb(v_row);
END;
$$;

COMMENT ON FUNCTION workspace.create_workspace(TEXT, TEXT, JSONB) IS
    'Создать продуктовое пространство в user-БД. Не вызывает CREATE DATABASE.';

CREATE OR REPLACE FUNCTION workspace.get_workspace(p_id UUID)
RETURNS JSONB
LANGUAGE sql
STABLE
AS $$
    SELECT to_jsonb(w)
    FROM workspace.workspaces w
    WHERE w.id = p_id;
$$;

COMMENT ON FUNCTION workspace.get_workspace(UUID) IS
    'Одно пространство по id. NULL если нет.';

CREATE OR REPLACE FUNCTION workspace.list_workspaces(
    p_include_archived BOOLEAN DEFAULT FALSE,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 50), 0), 500);
    v_offset INTEGER := GREATEST(COALESCE(p_offset, 0), 0);
    v_total BIGINT;
    v_items JSONB;
BEGIN
    SELECT count(*) INTO v_total
    FROM workspace.workspaces
    WHERE p_include_archived OR NOT is_archived;

    SELECT COALESCE(
        jsonb_agg(to_jsonb(t) ORDER BY t.updated_at DESC, t.id DESC),
        '[]'::jsonb
    )
    INTO v_items
    FROM (
        SELECT id, name, description, settings, is_archived, created_at, updated_at
        FROM workspace.workspaces
        WHERE p_include_archived OR NOT is_archived
        ORDER BY updated_at DESC, id DESC
        LIMIT v_limit
        OFFSET v_offset
    ) t;

    RETURN jsonb_build_object(
        'items', v_items,
        'total', v_total,
        'limit', v_limit,
        'offset', v_offset
    );
END;
$$;

COMMENT ON FUNCTION workspace.list_workspaces(BOOLEAN, INTEGER, INTEGER) IS
    'JSON-список пространств user-БД. По умолчанию без архивных.';

-- ── sessions ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION workspace.create_session(
    p_workspace_id UUID,
    p_title TEXT,
    p_agent_id UUID DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'::jsonb
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.sessions%ROWTYPE;
BEGIN
    IF p_workspace_id IS NULL THEN
        RAISE EXCEPTION 'workspace_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;

    IF p_title IS NULL OR btrim(p_title) = '' THEN
        RAISE EXCEPTION 'session title is empty'
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM workspace.workspaces WHERE id = p_workspace_id
    ) THEN
        RAISE EXCEPTION 'workspace % not found', p_workspace_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    INSERT INTO workspace.sessions (workspace_id, title, agent_id, metadata)
    VALUES (
        p_workspace_id,
        btrim(p_title),
        p_agent_id,
        COALESCE(p_metadata, '{}'::jsonb)
    )
    RETURNING * INTO v_row;

    UPDATE workspace.workspaces
       SET updated_at = NOW()
     WHERE id = p_workspace_id;

    RETURN to_jsonb(v_row);
END;
$$;

COMMENT ON FUNCTION workspace.create_session(UUID, TEXT, UUID, JSONB) IS
    'Создать сессию в пространстве. agent_id — непрозрачный UUID, без FK.';

CREATE OR REPLACE FUNCTION workspace.get_session(p_id UUID)
RETURNS JSONB
LANGUAGE sql
STABLE
AS $$
    SELECT to_jsonb(s)
    FROM workspace.sessions s
    WHERE s.id = p_id;
$$;

COMMENT ON FUNCTION workspace.get_session(UUID) IS
    'Одна сессия по id. NULL если нет.';

CREATE OR REPLACE FUNCTION workspace.list_sessions(
    p_workspace_id UUID,
    p_status TEXT DEFAULT NULL,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 50), 0), 500);
    v_offset INTEGER := GREATEST(COALESCE(p_offset, 0), 0);
    v_total BIGINT;
    v_items JSONB;
BEGIN
    IF p_workspace_id IS NULL THEN
        RAISE EXCEPTION 'workspace_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM workspace.workspaces WHERE id = p_workspace_id
    ) THEN
        RAISE EXCEPTION 'workspace % not found', p_workspace_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    SELECT count(*) INTO v_total
    FROM workspace.sessions
    WHERE workspace_id = p_workspace_id
      AND (p_status IS NULL OR status = p_status);

    SELECT COALESCE(
        jsonb_agg(to_jsonb(t) ORDER BY t.updated_at DESC, t.id DESC),
        '[]'::jsonb
    )
    INTO v_items
    FROM (
        SELECT id, workspace_id, title, status, agent_id, metadata,
               tab_open, agent_busy, created_at, updated_at
        FROM workspace.sessions
        WHERE workspace_id = p_workspace_id
          AND (p_status IS NULL OR status = p_status)
        ORDER BY updated_at DESC, id DESC
        LIMIT v_limit
        OFFSET v_offset
    ) t;

    RETURN jsonb_build_object(
        'items', v_items,
        'total', v_total,
        'limit', v_limit,
        'offset', v_offset
    );
END;
$$;

COMMENT ON FUNCTION workspace.list_sessions(UUID, TEXT, INTEGER, INTEGER) IS
    'JSON-список сессий пространства. p_status NULL — все статусы.';

-- ── timeline / events ────────────────────────────────────

CREATE OR REPLACE FUNCTION workspace.fetch_timeline(
    p_session_id UUID,
    p_before TIMESTAMPTZ DEFAULT NULL,
    p_limit INTEGER DEFAULT 100
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_limit INTEGER := LEAST(GREATEST(COALESCE(p_limit, 100), 0), 500);
    v_items JSONB;
    v_has_more BOOLEAN := FALSE;
    v_len INTEGER;
BEGIN
    IF p_session_id IS NULL THEN
        RAISE EXCEPTION 'session_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM workspace.sessions WHERE id = p_session_id
    ) THEN
        RAISE EXCEPTION 'session % not found', p_session_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    -- Берём limit+1, чтобы отдать has_more без второго запроса
    SELECT COALESCE(
        jsonb_agg(to_jsonb(t) ORDER BY t.created_at DESC, t.id DESC),
        '[]'::jsonb
    )
    INTO v_items
    FROM (
        SELECT id, session_id, kind, role, content, payload, created_at
        FROM workspace.events
        WHERE session_id = p_session_id
          AND (p_before IS NULL OR created_at < p_before)
        ORDER BY created_at DESC, id DESC
        LIMIT v_limit + 1
    ) t;

    v_len := jsonb_array_length(v_items);
    IF v_len > v_limit THEN
        v_has_more := TRUE;
        v_items := (
            SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
            FROM jsonb_array_elements(v_items) WITH ORDINALITY AS a(elem, n)
            WHERE n <= v_limit
        );
    END IF;

    RETURN jsonb_build_object(
        'items', v_items,
        'session_id', p_session_id,
        'limit', v_limit,
        'has_more', v_has_more
    );
END;
$$;

COMMENT ON FUNCTION workspace.fetch_timeline(UUID, TIMESTAMPTZ, INTEGER) IS
    'Лента сессии: message+action, newest first. Keyset: p_before = created_at курсора.';

CREATE OR REPLACE FUNCTION workspace.insert_event(
    p_session_id UUID,
    p_kind TEXT,
    p_role TEXT DEFAULT NULL,
    p_content TEXT DEFAULT NULL,
    p_payload JSONB DEFAULT '{}'::jsonb,
    p_id UUID DEFAULT NULL,
    p_created_at TIMESTAMPTZ DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_created_at TIMESTAMPTZ;
    v_row workspace.events%ROWTYPE;
BEGIN
    IF p_session_id IS NULL THEN
        RAISE EXCEPTION 'session_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;

    IF p_kind NOT IN ('message', 'action') THEN
        RAISE EXCEPTION 'invalid event kind: %', p_kind
            USING ERRCODE = 'check_violation';
    END IF;

    IF p_kind = 'message' AND (p_role IS NULL OR btrim(p_role) = '') THEN
        RAISE EXCEPTION 'message event requires role'
            USING ERRCODE = 'check_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM workspace.sessions WHERE id = p_session_id
    ) THEN
        RAISE EXCEPTION 'session % not found', p_session_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    v_created_at := COALESCE(p_created_at, NOW());

    -- Партиция месяца UTC; на горячем пути to_regclass без DDL-блокировки
    PERFORM workspace.ensure_event_partition(v_created_at);

    INSERT INTO workspace.events AS e (
        id, session_id, kind, role, content, payload, created_at
    )
    VALUES (
        COALESCE(p_id, gen_random_uuid()),
        p_session_id,
        p_kind,
        NULLIF(btrim(p_role), ''),
        p_content,
        COALESCE(p_payload, '{}'::jsonb),
        v_created_at
    )
    RETURNING * INTO v_row;

    RETURN to_jsonb(v_row);
END;
$$;

COMMENT ON FUNCTION workspace.insert_event(UUID, TEXT, TEXT, TEXT, JSONB, UUID, TIMESTAMPTZ) IS
    'Добавить событие в ленту. Append-only. Создаёт месячную партицию при необходимости.';
