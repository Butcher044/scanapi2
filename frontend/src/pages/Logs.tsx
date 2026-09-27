import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { RotateCw, ScrollText } from 'lucide-react'
import { useLogs } from '../hooks/useLogs'
import LogRow from '../components/logs/LogRow'

/** How close to the bottom still counts as "following" new lines, px */
const STICK_THRESHOLD = 24

function Note({ tone = 'muted', children }: { tone?: 'muted' | 'danger'; children: string }) {
  return (
    <p className={`px-4 py-3 text-sm ${tone === 'danger' ? 'text-danger' : 'text-ink-faint'}`}>{children}</p>
  )
}

export default function Logs() {
  const { events, hasMore, loading, loadingMore, error, loadMoreError, refresh, loadMore } = useLogs()
  const [refreshing, setRefreshing] = useState(false)
  // Console order: oldest on top, newest at the bottom
  const lines = useMemo(() => [...events].reverse(), [events])

  const viewport = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const anchor = useRef<number | null>(null)

  const onScroll = () => {
    const el = viewport.current
    if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD
  }

  // Older lines are prepended above: keep the visible ones in place.
  // Otherwise follow the tail while the reader is at the bottom.
  useLayoutEffect(() => {
    const el = viewport.current
    if (!el) return
    if (anchor.current !== null) {
      el.scrollTop += el.scrollHeight - anchor.current
      anchor.current = null
    } else if (following.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [lines, loading])

  const onLoadMore = () => {
    anchor.current = viewport.current?.scrollHeight ?? null
    void loadMore()
  }

  const onRefresh = async () => {
    setRefreshing(true)
    following.current = true
    await refresh()
    setRefreshing(false)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ScrollText className="h-5 w-5 text-ink-muted" aria-hidden="true" />
          <h1 className="text-2xl font-bold tracking-wide">Логи</h1>
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

      <div
        ref={viewport}
        onScroll={onScroll}
        role="log"
        aria-label="Журнал событий"
        className="h-[70vh] min-h-80 overflow-y-auto rounded-2xl border border-line bg-surface shadow-card"
      >
        {hasMore && (
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="flex w-full items-center justify-center border-b border-line/70 py-2.5 text-xs text-ink-muted hover:bg-raised hover:text-ink transition-colors disabled:opacity-60"
          >
            {loadingMore ? 'Загрузка…' : 'Показать более ранние записи'}
          </button>
        )}
        {loadMoreError && <Note tone="danger">{loadMoreError}</Note>}

        {loading ? (
          <Note>Загрузка…</Note>
        ) : lines.length === 0 && !error ? (
          <Note>Пока пусто — записи появятся после первого запуска парсинга</Note>
        ) : (
          <ul>
            {lines.map(event => <LogRow key={event.id} event={event} />)}
          </ul>
        )}

        {error && <Note tone="danger">{error}</Note>}
      </div>
    </div>
  )
}
