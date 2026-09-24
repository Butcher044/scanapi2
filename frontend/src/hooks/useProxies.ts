import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api'
import type { NewProxy, Proxy } from '../types'
import { useMounted } from './useMounted'

const replaceById = (list: Proxy[], next: Proxy) => list.map(p => (p.id === next.id ? next : p))
const withId = (ids: ReadonlySet<number>, id: number) => new Set([...ids, id])
const without = (ids: ReadonlySet<number>, id: number) => new Set([...ids].filter(x => x !== id))

export function isUsable(p: Proxy): boolean {
  return p.days_left === null || p.days_left >= 0
}

export function useProxies() {
  const mounted = useMounted()
  const [proxies, setProxies] = useState<Proxy[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState<ReadonlySet<number>>(new Set())
  const [deleting, setDeleting] = useState<ReadonlySet<number>>(new Set())
  const [checkingAll, setCheckingAll] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)
  // Synchronous guard: state updates land a render later, a double click does not wait for them
  const deletingNow = useRef<ReadonlySet<number>>(new Set())

  useEffect(() => {
    let cancelled = false
    setError(null)
    api.proxies()
      .then(r => { if (!cancelled) setProxies(r.proxies) })
      .catch(e => { if (!cancelled) setError(errorText(e, 'Не удалось загрузить прокси')) })
    return () => { cancelled = true }
  }, [loadAttempt])

  const reload = useCallback(() => setLoadAttempt(n => n + 1), [])

  /** Throws with a readable message so the form can show it next to the fields. */
  const add = useCallback(async (proxy: NewProxy) => {
    const created = await api.addProxy(proxy)
    if (!mounted.current) return
    setError(null)
    setProxies(list => [...(list ?? []), created])
  }, [mounted])

  const remove = useCallback(async (id: number) => {
    if (deletingNow.current.has(id)) return
    deletingNow.current = withId(deletingNow.current, id)
    setError(null)
    setDeleting(ids => withId(ids, id))
    try {
      await api.deleteProxy(id)
      if (mounted.current) setProxies(list => (list ?? []).filter(p => p.id !== id))
    } catch (e) {
      if (mounted.current) setError(errorText(e, 'Не удалось удалить прокси'))
    } finally {
      deletingNow.current = without(deletingNow.current, id)
      if (mounted.current) setDeleting(ids => without(ids, id))
    }
  }, [mounted])

  const check = useCallback(async (id: number) => {
    setError(null)
    setChecking(ids => withId(ids, id))
    try {
      const checked = await api.checkProxy(id)
      if (mounted.current) setProxies(list => replaceById(list ?? [], checked))
    } catch (e) {
      if (mounted.current) setError(errorText(e, 'Не удалось проверить прокси'))
    } finally {
      if (mounted.current) setChecking(ids => without(ids, id))
    }
  }, [mounted])

  const checkAll = useCallback(async () => {
    setError(null)
    setCheckingAll(true)
    try {
      const { proxies: checked } = await api.checkAllProxies()
      if (mounted.current) setProxies(list => checked.reduce(replaceById, list ?? []))
    } catch (e) {
      if (mounted.current) setError(errorText(e, 'Не удалось проверить прокси'))
    } finally {
      if (mounted.current) setCheckingAll(false)
    }
  }, [mounted])

  return { proxies, error, checking, deleting, checkingAll, reload, add, remove, check, checkAll }
}
