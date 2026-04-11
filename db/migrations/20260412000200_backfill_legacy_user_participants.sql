INSERT INTO users (user_id, display_name, metadata, created_at, updated_at)
SELECT
    COALESCE(p.user_id, p.participant_id),
    COALESCE(NULLIF(p.metadata->>'display_name', ''), p.participant_id::text),
    CASE
        WHEN p.metadata ? 'display_name' THEN p.metadata
        ELSE jsonb_build_object('display_name', COALESCE(NULLIF(p.metadata->>'display_name', ''), p.participant_id::text))
    END,
    p.created_at,
    p.updated_at
FROM participants p
LEFT JOIN users u ON COALESCE(p.user_id, p.participant_id) = u.user_id
WHERE p.participant_type = 'user'
  AND u.user_id IS NULL
ON CONFLICT (user_id) DO NOTHING;

UPDATE participants
SET user_id = participant_id
WHERE participant_type = 'user'
  AND user_id IS NULL;
