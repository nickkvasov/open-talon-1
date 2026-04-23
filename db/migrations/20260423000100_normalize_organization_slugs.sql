DO $$
DECLARE
    invalid_slug_count INTEGER;
    duplicate_slug_count INTEGER;
BEGIN
    WITH normalized AS (
        SELECT
            organization_id,
            regexp_replace(
                regexp_replace(lower(btrim(slug)), '[^a-z0-9]+', '-', 'g'),
                '(^-+|-+$)',
                '',
                'g'
            ) AS normalized_slug
        FROM organizations
    )
    SELECT COUNT(*)
    INTO invalid_slug_count
    FROM normalized
    WHERE normalized_slug = '';

    IF invalid_slug_count > 0 THEN
        RAISE EXCEPTION 'Cannot normalize organization slugs because one or more values are empty after normalization';
    END IF;

    WITH normalized AS (
        SELECT
            regexp_replace(
                regexp_replace(lower(btrim(slug)), '[^a-z0-9]+', '-', 'g'),
                '(^-+|-+$)',
                '',
                'g'
            ) AS normalized_slug
        FROM organizations
    )
    SELECT COUNT(*)
    INTO duplicate_slug_count
    FROM (
        SELECT normalized_slug
        FROM normalized
        GROUP BY normalized_slug
        HAVING COUNT(*) > 1
    ) AS duplicates;

    IF duplicate_slug_count > 0 THEN
        RAISE EXCEPTION 'Cannot normalize organization slugs because existing values would collide';
    END IF;
END
$$;

UPDATE organizations
SET slug = regexp_replace(
    regexp_replace(lower(btrim(slug)), '[^a-z0-9]+', '-', 'g'),
    '(^-+|-+$)',
    '',
    'g'
)
WHERE slug <> regexp_replace(
    regexp_replace(lower(btrim(slug)), '[^a-z0-9]+', '-', 'g'),
    '(^-+|-+$)',
    '',
    'g'
);

ALTER TABLE organizations
    ADD CONSTRAINT organizations_slug_format
    CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$');

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug_lower
    ON organizations (lower(slug));
