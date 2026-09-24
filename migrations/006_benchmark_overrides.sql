-- +goose Up
-- Ручные правки админа в таблице «Бенчмарк»: «есть» / «нет» поверх автоматического
-- сопоставления. Нет строки — ячейка считается автоматически (app/benchmark.py).
-- capability — ключ из app/benchmark_catalog.py; строки с исчезнувшим ключом игнорируются.
CREATE TABLE IF NOT EXISTS benchmark_overrides (
    capability TEXT        NOT NULL CHECK (char_length(capability) BETWEEN 1 AND 64),
    bank       TEXT        NOT NULL CHECK (char_length(bank) BETWEEN 1 AND 32),
    present    BOOLEAN     NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (capability, bank)
);
