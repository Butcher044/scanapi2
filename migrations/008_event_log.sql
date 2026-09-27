-- +goose Up
-- Журнал событий для вкладки «Логи» в админке: что делал сервис, простым языком.
-- Это не замена серверным логам (там трассировки), а понятная хроника для человека:
-- парсинг запущен, какой банк прошёл, какой упал, ушла ли сводка в Telegram.
-- Хранится KEEP_DAYS дней (app/event_log.py), чистится ежедневной задачей.
CREATE TABLE IF NOT EXISTS event_log (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level      VARCHAR(16) NOT NULL
        CHECK (level IN ('info', 'success', 'warning', 'error')),
    category   VARCHAR(16) NOT NULL
        CHECK (category IN ('parser', 'schedule', 'telegram', 'proxy', 'settings', 'system')),
    message    TEXT NOT NULL,
    details    TEXT
);

-- Лента читается от новых к старым по id (первичный ключ); этот индекс — для чистки.
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
