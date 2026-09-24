-- +goose Up
-- Скрытые сервисы и методы: то, что есть в исходных данных банка, но чего человек
-- не видит на дев-портале (закрытое пространство, устаревшая версия статьи, метод вне
-- меню, призрак из ленты обновлений). Такое не выбрасывается, а помечается: обычный
-- дашборд показывает только видимое, админ смотрит скрытое в отдельной вкладке.
-- hidden_reason — ключ из HIDDEN_REASON_* (bank_api_parser/parsers/base_parser.py).
ALTER TABLE methods
    ADD COLUMN IF NOT EXISTS hidden        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS hidden_reason VARCHAR(32);

-- Сервис скрыт, только если скрыты все его методы; частично скрытый сервис остаётся
-- видимым, из него выпадают лишь скрытые методы.
ALTER TABLE services
    ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;

-- Изменения пишутся и для скрытого, но в общую историю и в Telegram не попадают.
ALTER TABLE changes
    ADD COLUMN IF NOT EXISTS hidden BOOLEAN NOT NULL DEFAULT FALSE;

-- Скрытое обязано называть причину, и причина — только из известного набора.
-- Опечатка в парсере иначе молча заводит свою «категорию» в сводке админки.
ALTER TABLE methods DROP CONSTRAINT IF EXISTS methods_hidden_reason_check;
ALTER TABLE methods
    ADD CONSTRAINT methods_hidden_reason_check CHECK (NOT hidden OR hidden_reason IS NOT NULL);
ALTER TABLE methods DROP CONSTRAINT IF EXISTS methods_hidden_reason_known;
ALTER TABLE methods
    ADD CONSTRAINT methods_hidden_reason_known CHECK (
        hidden_reason IS NULL
        OR hidden_reason IN ('private', 'superseded', 'not_in_menu', 'ghost')
    );

CREATE INDEX IF NOT EXISTS idx_methods_hidden  ON methods(service_id) WHERE hidden;
CREATE INDEX IF NOT EXISTS idx_services_hidden ON services(snapshot_id) WHERE hidden;

-- Один и тот же «последний снимок банка» нужен diff-у, чистке, дашборду и бенчмарку —
-- все они ходят по (bank, id DESC), см. app/repository.py:get_latest_snapshot.
CREATE INDEX IF NOT EXISTS idx_snapshots_bank_id ON snapshots(bank, id DESC);

-- Индекса по скрытым changes здесь нет намеренно: скрытые изменения пишутся, но
-- отдельной вкладки для них нет, а платить за индекс на каждой вставке — незачем.
