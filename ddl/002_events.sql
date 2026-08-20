-- 002_events.sql: партиции events RANGE по created_at (месяц UTC)
--
-- register_schema не умеет PARTITION BY — он создаёт обычную кучу
-- с PK (id, created_at). Здесь идемпотентно:
--   relkind = 'p' → уже партиционирована, ничего не делаем
--   relkind = 'r' → куча: переименовать, создать parent, перелить, дропнуть
--   нет таблицы  → создать parent сразу как partitioned
--
-- Дефолтной партиции нет: иначе нельзя отрезать месяц без переливки.
-- Границы месяца — UTC, чтобы session TimeZone не двигал нарезы.

DO $$
DECLARE
    v_relkind "char";
BEGIN
    SELECT c.relkind INTO v_relkind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'workspace'
      AND c.relname = 'events';

    IF v_relkind = 'p' THEN
        RETURN;
    END IF;

    IF v_relkind = 'r' THEN
        ALTER TABLE workspace.events RENAME TO events_unpartitioned;
    END IF;

    CREATE TABLE workspace.events (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        session_id UUID NOT NULL,
        kind VARCHAR(32) NOT NULL,
        role VARCHAR(32),
        content TEXT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT pk_events PRIMARY KEY (id, created_at),
        CONSTRAINT fk_events_session_id
            FOREIGN KEY (session_id)
            REFERENCES workspace.sessions(id)
            ON DELETE CASCADE,
        CONSTRAINT chk_events_kind
            CHECK (kind IN ('message', 'action')),
        CONSTRAINT chk_events_message_role
            CHECK (kind <> 'message' OR role IS NOT NULL)
    ) PARTITION BY RANGE (created_at);

    COMMENT ON TABLE workspace.events IS
        'Лента сессии: сообщения и действия. Append-only. Партиции по месяцу UTC.';
    COMMENT ON COLUMN workspace.events.kind IS
        'Дискриминатор: message — сообщение, action — действие агента/инструмента.';
    COMMENT ON COLUMN workspace.events.role IS
        'Роль автора сообщения (user/assistant/system/tool). Обязательна при kind=message.';
    COMMENT ON COLUMN workspace.events.payload IS
        'Структурированное тело события (tool call, метаданные сообщения).';
    COMMENT ON COLUMN workspace.events.created_at IS
        'Время события и ключ RANGE-партиции. Не обновляется.';
END $$;

-- Создать партицию на месяц p_ts, если её ещё нет.
-- to_regclass — без AccessExclusiveLock на горячем пути insert_event.
CREATE OR REPLACE FUNCTION workspace.ensure_event_partition(p_ts TIMESTAMPTZ)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_start TIMESTAMPTZ;
    v_end   TIMESTAMPTZ;
    v_name  TEXT;
BEGIN
    IF p_ts IS NULL THEN
        RAISE EXCEPTION 'ensure_event_partition: timestamp is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;

    -- Месяц в UTC: AT TIME ZONE даёт timestamp without tz, обратная конвертация — timestamptz
    v_start := date_trunc('month', p_ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    v_end := v_start + INTERVAL '1 month';
    v_name := format('events_%s', to_char(v_start AT TIME ZONE 'UTC', 'YYYYMM'));

    IF to_regclass(format('workspace.%I', v_name)) IS NOT NULL THEN
        RETURN;
    END IF;

    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS workspace.%I PARTITION OF workspace.events FOR VALUES FROM (%L) TO (%L)',
        v_name, v_start, v_end
    );
END;
$$;

COMMENT ON FUNCTION workspace.ensure_event_partition(TIMESTAMPTZ) IS
    'Создать месячную партицию events на timestamp (UTC), если отсутствует.';

-- Создать партиции от p_from на p_months вперёд (включительно текущий месяц p_from).
CREATE OR REPLACE FUNCTION workspace.ensure_event_partitions(
    p_from TIMESTAMPTZ DEFAULT NOW(),
    p_months INTEGER DEFAULT 3
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_i INTEGER;
    v_ts TIMESTAMPTZ;
    v_months INTEGER;
BEGIN
    v_months := GREATEST(COALESCE(p_months, 0), 0);
    v_ts := date_trunc('month', COALESCE(p_from, NOW()) AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';

    FOR v_i IN 0..v_months LOOP
        PERFORM workspace.ensure_event_partition(v_ts + (v_i || ' months')::INTERVAL);
    END LOOP;
END;
$$;

COMMENT ON FUNCTION workspace.ensure_event_partitions(TIMESTAMPTZ, INTEGER) IS
    'Провижининг партиций events: p_from и p_months месяцев вперёд.';

-- Перелить данные из кучи register_schema (на template пусто).
DO $$
BEGIN
    IF to_regclass('workspace.events_unpartitioned') IS NULL THEN
        RETURN;
    END IF;

    IF EXISTS (SELECT 1 FROM workspace.events_unpartitioned LIMIT 1) THEN
        PERFORM workspace.ensure_event_partition(g.ts)
        FROM generate_series(
            date_trunc('month', (SELECT min(created_at) AT TIME ZONE 'UTC' FROM workspace.events_unpartitioned))
                AT TIME ZONE 'UTC',
            date_trunc('month', (SELECT max(created_at) AT TIME ZONE 'UTC' FROM workspace.events_unpartitioned))
                AT TIME ZONE 'UTC',
            INTERVAL '1 month'
        ) AS g(ts);

        INSERT INTO workspace.events
        SELECT id, session_id, kind, role, content, payload, created_at
        FROM workspace.events_unpartitioned;
    END IF;

    DROP TABLE workspace.events_unpartitioned;
END $$;

-- Текущий месяц UTC, предыдущий (хвост ленты) и три месяца вперёд
SELECT workspace.ensure_event_partition(NOW() - INTERVAL '1 month');
SELECT workspace.ensure_event_partitions(NOW(), 3);

-- Лента сессии: свежие события сверху. Партиционированный индекс.
CREATE INDEX IF NOT EXISTS idx_events_session_created
    ON workspace.events (session_id, created_at DESC);
