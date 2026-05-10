-- Adds the runtime write permission used to resume failed durable tasks after
-- recoverable provider outages such as quota exhaustion or provider auth fixes.

UPDATE iam_role_definitions
SET permissions = permissions || '["organization.runtime.write"]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"runtime_resume_permission": true}'::jsonb
WHERE subject_kind = 'agent'
  AND permissions ? 'organization.runtime.read'
  AND NOT permissions ? 'organization.runtime.write';
