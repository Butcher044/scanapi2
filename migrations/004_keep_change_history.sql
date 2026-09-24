-- +goose Up
-- История изменений не должна пропадать при очистке старых снапшотов.
ALTER TABLE changes ALTER COLUMN snapshot_id DROP NOT NULL;
ALTER TABLE changes DROP CONSTRAINT IF EXISTS changes_snapshot_id_fkey;
ALTER TABLE changes
    ADD CONSTRAINT changes_snapshot_id_fkey
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_changes_snapshot ON changes(snapshot_id);
-- История растёт бессрочно: фильтр по банку + сортировка по дате.
CREATE INDEX IF NOT EXISTS idx_changes_bank_detected ON changes(bank, detected_at DESC);

-- Длинные названия/пути порталов не должны валить импорт.
ALTER TABLE services ALTER COLUMN name TYPE TEXT;
ALTER TABLE methods  ALTER COLUMN name TYPE TEXT;
ALTER TABLE methods  ALTER COLUMN path TYPE TEXT;
ALTER TABLE fields   ALTER COLUMN name TYPE TEXT;
ALTER TABLE changes  ALTER COLUMN entity_name TYPE TEXT;
ALTER TABLE changes  ALTER COLUMN entity_path TYPE TEXT;
-- Индекс по path ни одним запросом не используется, а на TEXT рискует
-- упереться в предел размера строки btree (~2.7 КБ).
DROP INDEX IF EXISTS idx_methods_path;

-- Таблица settings (осталась от Go-версии) нигде не используется.
DROP TABLE IF EXISTS settings;
