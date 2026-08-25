-- 007_functions_nodes.sql: SQL API nodes + delete/update session tabs

CREATE OR REPLACE FUNCTION workspace.delete_workspace(p_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.workspaces%ROWTYPE;
BEGIN
    IF p_id IS NULL THEN
        RAISE EXCEPTION 'workspace_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;
    DELETE FROM workspace.workspaces
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.set_workspace_root(p_id UUID, p_root TEXT)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.workspaces%ROWTYPE;
BEGIN
    UPDATE workspace.workspaces
       SET root_path = p_root, updated_at = NOW()
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.delete_session(p_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.sessions%ROWTYPE;
BEGIN
    DELETE FROM workspace.sessions
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.set_session_flags(
    p_id UUID,
    p_tab_open BOOLEAN DEFAULT NULL,
    p_agent_busy BOOLEAN DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.sessions%ROWTYPE;
BEGIN
    UPDATE workspace.sessions
       SET tab_open = COALESCE(p_tab_open, tab_open),
           agent_busy = COALESCE(p_agent_busy, agent_busy),
           updated_at = NOW()
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.close_all_tabs(p_workspace_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE workspace.sessions
       SET tab_open = FALSE, updated_at = NOW()
     WHERE workspace_id = p_workspace_id
       AND tab_open IS TRUE;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN jsonb_build_object('closed', v_count);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.create_node(
    p_workspace_id UUID,
    p_parent_id UUID,
    p_kind TEXT,
    p_name TEXT,
    p_rel_path TEXT,
    p_size_bytes BIGINT DEFAULT 0,
    p_file_count INTEGER DEFAULT 0
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.nodes%ROWTYPE;
BEGIN
    IF p_workspace_id IS NULL THEN
        RAISE EXCEPTION 'workspace_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;
    IF p_kind NOT IN ('folder', 'file') THEN
        RAISE EXCEPTION 'invalid node kind: %', p_kind
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_name IS NULL OR btrim(p_name) = '' THEN
        RAISE EXCEPTION 'node name is empty'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM workspace.workspaces WHERE id = p_workspace_id) THEN
        RAISE EXCEPTION 'workspace % not found', p_workspace_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF p_parent_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM workspace.nodes
         WHERE id = p_parent_id AND workspace_id = p_workspace_id AND kind = 'folder'
    ) THEN
        RAISE EXCEPTION 'parent folder not found'
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    INSERT INTO workspace.nodes (
        workspace_id, parent_id, kind, name, rel_path, size_bytes, file_count
    )
    VALUES (
        p_workspace_id,
        p_parent_id,
        p_kind,
        left(btrim(p_name), 255),
        p_rel_path,
        COALESCE(p_size_bytes, 0),
        COALESCE(p_file_count, 0)
    )
    RETURNING * INTO v_row;

    UPDATE workspace.workspaces SET updated_at = NOW() WHERE id = p_workspace_id;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.list_nodes(
    p_workspace_id UUID,
    p_parent_id UUID DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_items JSONB;
BEGIN
    IF p_workspace_id IS NULL THEN
        RAISE EXCEPTION 'workspace_id is NULL'
            USING ERRCODE = 'not_null_violation';
    END IF;
    SELECT COALESCE(
        jsonb_agg(to_jsonb(t) ORDER BY t.kind DESC, t.name ASC),
        '[]'::jsonb
    )
    INTO v_items
    FROM (
        SELECT id, workspace_id, parent_id, kind, name, rel_path,
               size_bytes, file_count, created_at, updated_at
          FROM workspace.nodes
         WHERE workspace_id = p_workspace_id
           AND (
                (p_parent_id IS NULL AND parent_id IS NULL)
                OR parent_id = p_parent_id
           )
    ) t;
    RETURN jsonb_build_object('items', v_items);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.get_node(p_id UUID)
RETURNS JSONB
LANGUAGE sql
STABLE
AS $$
    SELECT to_jsonb(n) FROM workspace.nodes n WHERE n.id = p_id;
$$;

CREATE OR REPLACE FUNCTION workspace.delete_node(p_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row workspace.nodes%ROWTYPE;
BEGIN
    DELETE FROM workspace.nodes
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;

CREATE OR REPLACE FUNCTION workspace.touch_folder_stats(
    p_id UUID,
    p_file_count INTEGER,
    p_size_bytes BIGINT
)
RETURNS VOID
LANGUAGE sql
AS $$
    UPDATE workspace.nodes
       SET file_count = p_file_count,
           size_bytes = p_size_bytes,
           updated_at = NOW()
     WHERE id = p_id AND kind = 'folder';
$$;
