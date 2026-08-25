-- 010_patch_settings.sql: JSONB settings (exclude_paths и пр.)

CREATE OR REPLACE FUNCTION workspace.patch_settings(p_id UUID, p_settings JSONB)
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
    UPDATE workspace.workspaces
       SET settings = COALESCE(settings, '{}'::jsonb) || COALESCE(p_settings, '{}'::jsonb),
           updated_at = NOW()
     WHERE id = p_id
    RETURNING * INTO v_row;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    RETURN to_jsonb(v_row);
END;
$$;
