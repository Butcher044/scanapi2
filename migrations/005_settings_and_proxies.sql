-- +goose Up
-- Настройки, которые админ меняет из интерфейса (время парсинга, прокси вкл/выкл).
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT        NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Исходящие прокси для парсеров. url содержит логин/пароль прокси — наружу
-- отдаётся только в замаскированном виде.
CREATE TABLE IF NOT EXISTS proxies (
    id                 SERIAL PRIMARY KEY,
    url                TEXT        NOT NULL UNIQUE CHECK (char_length(url) BETWEEN 1 AND 500),
    label              TEXT        NOT NULL DEFAULT '' CHECK (char_length(label) <= 100),
    expires_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at    TIMESTAMPTZ,
    last_ok            BOOLEAN,
    last_ip            TEXT,
    last_country       TEXT,
    last_latency_ms    INTEGER,
    last_error         TEXT,
    expiry_notified_at TIMESTAMPTZ
);
