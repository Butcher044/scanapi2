import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api'
import type { LogEvent } from '../types'

const PAGE_SIZE = 100
export const REFRESH_MS = 10_000

/**
 * Newest page on top of what is already loaded: keeps "Показать ещё" pages intact.
 * If the page is full and does not reach what we already have, there may be a gap
 * between them — then start over from the fresh page (older ones stay reachable
 * through "Показать ещё") instead of silently skipping events.
 */
function mergeFresh(fresh: LogEvent[], current: LogEvent[]): { events: LogEvent[]; reset: boolean } {
  if (fresh.length === 0) return { events: current, reset: false }
  const oldestFresh = fresh[fresh.length - 1].id
  const newestKnown = current[0]?.id ?? 0
  if (fresh.length >= PAGE_SIZE && oldestFresh > newestKnown + 1) return { events: fresh, reset: true }
  return { events: [...fresh, ...current.filter(e => e.id < oldestFresh)], reset: false }
}

/**
 * Data layer of the admin "Логи" console: first page, silent polling for new
 * events while the tab is visible, and older pages on demand. Responses that
 * arrive after unmount are dropped (the generation counter).
 */
export function useLogs() {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null)
  const generation = useRef(0)

  const query = useCallback((before?: number) => api.logs({ before, limit: PAGE_SIZE }), [])

  // First page
  useEffect(() => {
    const gen = ++generation.current
    setLoading(true)
    setError(null)
    setLoadMoreError(null)
    setEvents([])
    setHasMore(false)
    query()
      .then(r => {
        if (gen !== generation.current) return
        setEvents(r.events)
        setHasMore(r.has_more)
      })
      .catch(e => { if (gen === generation.current) setError(errorText(e, 'Не удалось загрузить логи')) })
      .finally(() => { if (gen === generation.current) setLoading(false) })
  }, [query])

  const refresh = useCallback(async () => {
    const gen = generation.current
    try {
      const r = await query()
      if (gen !== generation.current) return
      setEvents(current => {
        const merged = mergeFresh(r.events, current)
        if (merged.reset) setHasMore(true)
        return merged.events
      })
      setError(null)
    } catch (e) {
      if (gen === generation.current) setError(errorText(e, 'Не удалось обновить логи'))
    }
  }, [query])

  // Silent polling; paused while the browser tab is hidden
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh()
    }, REFRESH_MS)
    const onVisible = () => { if (document.visibilityState === 'visible') void refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  // Invalidates the generation on unmount so late responses are ignored
  useEffect(() => () => { generation.current += 1 }, [])

  const loadMore = useCallback(async () => {
    const oldest = events[events.length - 1]?.id
    if (oldest == null) return
    const gen = generation.current
    setLoadingMore(true)
    setLoadMoreError(null)
    try {
      const r = await query(oldest)
      if (gen !== generation.current) return
      setEvents(current => [...current, ...r.events.filter(e => e.id < oldest)])
      setHasMore(r.has_more)
    } catch (e) {
      if (gen === generation.current) setLoadMoreError(errorText(e, 'Не удалось загрузить более старые записи'))
    } finally {
      if (gen === generation.current) setLoadingMore(false)
    }
  }, [events, query])

  return { events, hasMore, loading, loadingMore, error, loadMoreError, refresh, loadMore }
}
