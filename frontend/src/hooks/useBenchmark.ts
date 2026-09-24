import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api'
import type { Benchmark } from '../types'
import { useMounted } from './useMounted'

export const cellId = (capability: string, bank: string) => `${capability}:${bank}`

const withId = (ids: ReadonlySet<string>, id: string) => new Set([...ids, id])
const without = (ids: ReadonlySet<string>, id: string) => new Set([...ids].filter(x => x !== id))

export function useBenchmark(refresh: number) {
  const mounted = useMounted()
  const [data, setData] = useState<Benchmark | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<ReadonlySet<string>>(new Set())
  const [loadAttempt, setLoadAttempt] = useState(0)
  // Synchronous guard: a double click must not send two writes for one cell
  const savingNow = useRef<ReadonlySet<string>>(new Set())
  // Every write returns the whole matrix: a response older than the one already shown
  // must not replace it, otherwise a late answer hides a newer edit
  const lastWrite = useRef(0)
  const shownWrite = useRef(0)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api.benchmark()
      .then(r => { if (!cancelled) setData(r) })
      .catch(e => { if (!cancelled) setError(errorText(e, 'Не удалось загрузить бенчмарк')) })
    return () => { cancelled = true }
  }, [refresh, loadAttempt])

  const reload = useCallback(() => setLoadAttempt(n => n + 1), [])

  const override = useCallback(async (capability: string, bank: string, present: boolean | null) => {
    const id = cellId(capability, bank)
    if (savingNow.current.has(id)) return
    savingNow.current = withId(savingNow.current, id)
    setError(null)
    setSaving(ids => withId(ids, id))
    const write = ++lastWrite.current
    try {
      const next = await api.setBenchmarkOverride(capability, bank, present)
      if (mounted.current && write > shownWrite.current) {
        shownWrite.current = write
        setData(next)
      }
    } catch (e) {
      if (mounted.current) setError(errorText(e, 'Не удалось сохранить правку'))
    } finally {
      savingNow.current = without(savingNow.current, id)
      if (mounted.current) setSaving(ids => without(ids, id))
    }
  }, [mounted])

  return { data, error, saving, reload, override }
}
