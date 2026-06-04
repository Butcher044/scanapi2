-- +goose Up
ALTER TABLE methods ADD COLUMN IF NOT EXISTS path VARCHAR(500);
CREATE INDEX IF NOT EXISTS idx_methods_path ON methods(path);

-- +goose Down
DROP INDEX IF EXISTS idx_methods_path;
ALTER TABLE methods DROP COLUMN IF EXISTS path;
