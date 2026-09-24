import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api'
import type { HiddenSummary, HiddenService, HiddenMethod } from '../types'
import { useMounted } from './useMounted'

/**
 * Data layer of the admin "Скрытые сервисы" tab. All three hooks follow the
 * same rules as useBenchmark: never setState after unmount, and never let a
 * late response overwrite state that belongs to a newer request.
 */

export function useHiddenSummary() {
  const mounted = useMounted()
  const [data, setData] = useState<HiddenSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.hiddenSummary()
      .then(s => { if (!cancelled) setData(s) })
      .catch(e => { if (!cancelled) setError(errorText(e, 'Не удалось загрузить сводку по скрытым сервисам')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [attempt, mounted])

  const reload = useCallback(() => setAttempt(n => n + 1), [])

  return { data, error, loading, reload }
}

export function useHiddenServices(bank: string) {
  const [data, setData] = useState<HiddenService[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setData(null)
    setError(null)
    api.hiddenServices(bank)
      .then(r => { if (!cancelled) setData(r.services ?? []) })
      .catch(e => {
        if (!cancelled) {
          setError(errorText(e, 'Не удалось загрузить скрытые сервисы'))
          setData([])
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [bank])

  return { data, error, loading }
}

/** Methods are fetched lazily, when a service row is opened for the first time. */
export function useHiddenMethods(serviceId: number) {
  const mounted = useMounted()
  const [data, setData] = useState<HiddenMethod[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // Synchronous guard: a double click must not fire two identical requests
  const fetching = useRef(false)

  const load = useCallback(async () => {
    if (fetching.current || data !== null) return
    fetching.current = true
    setLoading(true)
    setError(null)
    try {
      const r = await api.hiddenMethods(serviceId)
      if (mounted.current) setData(r.methods ?? [])
    } catch (e) {
      if (mounted.current) {
        setError(errorText(e, 'Не удалось загрузить скрытые методы'))
        setData([])
      }
    } finally {
      fetching.current = false
      if (mounted.current) setLoading(false)
    }
  }, [serviceId, data, mounted])

  return { data, error, loading, load }
}
