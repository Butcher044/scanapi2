-- +goose Up
-- Создание таблиц для мониторинга API банков

-- Снапшоты (временные срезы данных)
CREATE TABLE IF NOT EXISTS snapshots (
    id SERIAL PRIMARY KEY,
    bank VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_snapshots_bank ON snapshots(bank);
CREATE INDEX IF NOT EXISTS idx_snapshots_created ON snapshots(created_at);

-- Сервисы (API сервисы банков)
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    url TEXT,
    UNIQUE(snapshot_id, name)
);

CREATE INDEX IF NOT EXISTS idx_services_snapshot ON services(snapshot_id);

-- Методы API
CREATE TABLE IF NOT EXISTS methods (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    http_method VARCHAR(10) NOT NULL,
    url TEXT,
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_methods_service ON methods(service_id);

-- Поля ответов
CREATE TABLE IF NOT EXISTS fields (
    id SERIAL PRIMARY KEY,
    method_id INTEGER NOT NULL REFERENCES methods(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    field_type VARCHAR(50),
    required BOOLEAN DEFAULT FALSE,
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_fields_method ON fields(method_id);

-- История изменений
CREATE TABLE IF NOT EXISTS changes (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    bank VARCHAR(50) NOT NULL,
    change_type VARCHAR(20) NOT NULL,
    change_action VARCHAR(20) NOT NULL,
    entity_name VARCHAR(255) NOT NULL,
    entity_path VARCHAR(500),
    old_value TEXT,
    new_value TEXT,
    url TEXT,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_changes_bank ON changes(bank);
CREATE INDEX IF NOT EXISTS idx_changes_detected ON changes(detected_at);

-- Подписчики Telegram
CREATE TABLE IF NOT EXISTS telegram_subscribers (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL UNIQUE,
    username VARCHAR(255),
    subscribed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Настройки
CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT
);

-- +goose Down
DROP TABLE IF EXISTS settings CASCADE;
DROP TABLE IF EXISTS telegram_subscribers CASCADE;
DROP TABLE IF EXISTS changes CASCADE;
DROP TABLE IF EXISTS fields CASCADE;
DROP TABLE IF EXISTS methods CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS snapshots CASCADE;