-- 009_rewrite_paths.sql: сдвиг rel_path после move на диске

CREATE OR REPLACE FUNCTION workspace.rewrite_paths(
    p_workspace_id UUID,
    p_old TEXT,
    p_new TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF p_workspace_id IS NULL OR p_old IS NULL OR p_new IS NULL OR p_old = '' THEN
        RAISE EXCEPTION 'invalid rewrite_paths args'
            USING ERRCODE = 'not_null_violation';
    END IF;
    UPDATE workspace.nodes
       SET rel_path = CASE
               WHEN rel_path = p_old THEN p_new
               ELSE p_new || substr(rel_path, length(p_old) + 1)
           END,
           name = CASE
               WHEN rel_path = p_old THEN regexp_replace(p_new, '^.*/', '')
               ELSE name
           END,
           updated_at = NOW()
     WHERE workspace_id = p_workspace_id
       AND (rel_path = p_old OR rel_path LIKE p_old || '/%');
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;
