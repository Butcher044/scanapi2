-- +goose Up
ALTER TABLE methods
    ADD COLUMN IF NOT EXISTS request_example  JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS response_example JSONB NOT NULL DEFAULT '{}';
