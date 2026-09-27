import { useMemo, useState } from 'react'
import { Loader2, RotateCw, ScrollText } from 'lucide-react'
import { REFRESH_MS, useLogs, type LogFilters } from '../hooks/useLogs'
import type { LogEvent } from '../types'
import LogFilterBar from '../components/logs/LogFilterBar'
import LogRow from '../components/logs/LogRow'
import { dayTitle } from '../components/logs/logMeta'

interface DayGroup {
  date: string
  events: LogEvent[]
}

/** Events arrive newest first, so consecutive runs of one date form a day. */
function groupByDay(events: LogEvent[]): DayGroup[] {
  return events.reduce<DayGroup[]>((groups, event) => {
    const last = groups[groups.length - 1]
    return last && last.date === event.date
      ? [...groups.slice(0, -1), { ...last, events: [...last.events, event] }]
      : [...groups, { date: event.date, events: [event] }]
  }, [])
}

const NO_FILTERS: LogFilters = { level: null, category: null }

export default function Logs() {
  const [filters, setFilters] = useState<LogFilters>(NO_FILTERS)
  const { events, hasMore, loading, loadingMore, error, loadMoreError, refresh, loadMore } = useLogs(filters)
  const [refreshing, setRefreshing] = useState(false)
  const groups = useMemo(() => groupByDay(events), [events])
  const filtered = filters.level !== null || filters.category !== null

  const onRefresh = async () => {
    setRefreshing(true)
    await refresh()
    setRefreshing(false)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <ScrollText className="h-5 w-5 text-ink-muted" aria-hidden="true" />
            <h1 className="text-2xl font-bold tracking-wide">Логи</h1>
          </div>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Что делал сервис: запуски парсинга, результат по каждому банку, отправка сообщений
            в Telegram, изменения настроек. Время московское, записи хранятся 30 дней,
            лента обновляется сама раз в {REFRESH_MS / 1000} секунд.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="press flex items-center gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2 text-xs text-ink hover:bg-raised transition-colors disabled:opacity-60"
        >
          <RotateCw size={13} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />
          Обновить
        </button>
      </div>

      <div className="rounded-2xl border border-line bg-surface p-5 shadow-card">
        <LogFilterBar filters={filters} onChange={setFilters} />
      </div>

      {error && (
        <div role="alert" className="rounded-2xl border border-danger/25 bg-surface px-5 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-ink-muted">
          <Loader2 size={18} className="animate-spin" aria-hidden="true" />
          <span className="text-sm">Загрузка…</span>
        </div>
      ) : events.length === 0 ? (
        !error && (
          <div className="rounded-2xl border border-line bg-surface py-16 text-center text-sm text-ink-faint shadow-card">
            {filtered ? 'Под выбранный фильтр записей нет' : 'Пока ничего не произошло — записи появятся после первого запуска парсинга'}
          </div>
        )
      ) : (
        <div className="flex flex-col gap-6">
          {groups.map(group => (
            <section key={group.date} aria-labelledby={`logs-day-${group.date}`}>
              <h2 id={`logs-day-${group.date}`} className="mb-2 px-1 text-xs font-semibold uppercase tracking-wider text-ink-faint">
                {dayTitle(group.date)}
              </h2>
              <ul className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
                {group.events.map(event => <LogRow key={event.id} event={event} />)}
              </ul>
            </section>
          ))}
          {loadMoreError && (
            <p role="alert" className="text-center text-sm text-danger">{loadMoreError}</p>
          )}
          {hasMore && (
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              className="press mx-auto flex items-center gap-2 rounded-xl border border-line-strong bg-surface px-4 py-2 text-sm text-ink hover:bg-raised transition-colors disabled:opacity-60"
            >
              {loadingMore && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
              Показать ещё
            </button>
          )}
        </div>
      )}
    </div>
  )
}
