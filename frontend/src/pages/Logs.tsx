import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { RotateCw, ScrollText } from 'lucide-react'
import { useLogs } from '../hooks/useLogs'
import LogRow from '../components/logs/LogRow'

/** How close to the bottom still counts as "following" new lines, px */
const STICK_THRESHOLD = 24

function ConsoleNote({ tone = 'dim', children }: { tone?: 'dim' | 'err'; children: string }) {
  return (
    <p className={`px-4 py-0.5 ${tone === 'err' ? 'text-console-err' : 'text-console-dim'}`}>{children}</p>
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
        className="h-[70vh] min-h-80 overflow-y-auto rounded-2xl border border-console-line bg-console py-3 font-mono text-xs leading-relaxed shadow-card"
      >
        {hasMore && (
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="press mx-4 mb-2 text-console-info hover:underline disabled:opacity-60"
          >
            {loadingMore ? 'загрузка…' : '↑ показать более ранние записи'}
          </button>
        )}
        {loadMoreError && <ConsoleNote tone="err">{loadMoreError}</ConsoleNote>}

        {loading ? (
          <ConsoleNote>загрузка…</ConsoleNote>
        ) : lines.length === 0 && !error ? (
          <ConsoleNote>Пока пусто — записи появятся после первого запуска парсинга</ConsoleNote>
        ) : (
          <ul>
            {lines.map(event => <LogRow key={event.id} event={event} />)}
          </ul>
        )}

        {error && <ConsoleNote tone="err">{error}</ConsoleNote>}
      </div>
    </div>
  )
}
