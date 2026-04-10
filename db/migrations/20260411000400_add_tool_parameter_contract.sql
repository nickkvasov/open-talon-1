ALTER TABLE system_tools
    ADD COLUMN IF NOT EXISTS parameter_contract JSONB NOT NULL DEFAULT '{"parameters":[],"additional_properties":false}'::jsonb;
