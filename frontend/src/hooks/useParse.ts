import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { ParseStatus } from '../types'

const POLL_MS = 3000
const MAX_POLL_FAILURES = 5

export function useParse(onFinished: () => void) {
  const [status, setStatus] = useState<ParseStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const generation = useRef(0)  // bumps on stop(); a stale watch() chain sees the mismatch and ends
  const failures = useRef(0)
  const onFinishedRef = useRef(onFinished)
  useEffect(() => { onFinishedRef.current = onFinished }, [onFinished])

  const stop = useCallback(() => {
    generation.current += 1
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  // Returns true while a parse is running
  const poll = useCallback(async (): Promise<boolean> => {
    try {
      const s = await api.parseStatus()
      failures.current = 0
      setStatus(s)
      return s.running
    } catch {
      failures.current += 1
      if (failures.current >= MAX_POLL_FAILURES) {
        setError('Сервер не отвечает — статус парсинга неизвестен')
        // Unknown ≠ running: release the button so the user is not locked out
        setStatus(prev => (prev ? { ...prev, running: false } : prev))
        return false
      }
      return true
    }
  }, [])

  const watch = useCallback(async () => {
    stop()
    const gen = generation.current
    const running = await poll()
    if (gen !== generation.current) return  // superseded by a newer watch() or unmount
    if (running) {
      timer.current = setTimeout(watch, POLL_MS)
    } else {
      onFinishedRef.current()
    }
  }, [poll, stop])

  // Pick up a parse that is already running (scheduled or started from another tab)
  useEffect(() => {
    let cancelled = false
    api.parseStatus()
      .then(s => {
        if (cancelled) return
        setStatus(s)
        if (s.running) void watch()
      })
      .catch(() => { /* status is optional on first load; the button still works */ })
    return () => { cancelled = true; stop() }
  }, [watch, stop])

  const start = useCallback(async () => {
    setError(null)
    setStarting(true)
    try {
      if (await api.startParse() === 'forbidden') {
        setError('Запуск парсинга доступен только администратору')
        return false
      }
      failures.current = 0
      await watch()
      return true
    } catch {
      setError('Не удалось запустить парсинг')
      return false
    } finally {
      setStarting(false)
    }
  }, [watch])

  return { status, error, starting, start, clearError: () => setError(null) }
}
