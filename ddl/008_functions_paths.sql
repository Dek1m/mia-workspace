-- 008_functions_paths.sql: поиск ноды по rel_path и полный список

CREATE OR REPLACE FUNCTION workspace.get_node_by_path(
    p_workspace_id UUID,
    p_rel_path TEXT
)
RETURNS JSONB
LANGUAGE sql
STABLE
AS $$
    SELECT to_jsonb(n)
      FROM workspace.nodes n
     WHERE n.workspace_id = p_workspace_id
       AND n.rel_path = p_rel_path
     LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION workspace.list_all_nodes(p_workspace_id UUID)
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
        jsonb_agg(to_jsonb(t) ORDER BY t.rel_path ASC),
        '[]'::jsonb
    )
    INTO v_items
    FROM (
        SELECT id, workspace_id, parent_id, kind, name, rel_path,
               size_bytes, file_count, created_at, updated_at
          FROM workspace.nodes
         WHERE workspace_id = p_workspace_id
    ) t;
    RETURN jsonb_build_object('items', v_items);
END;
$$;
