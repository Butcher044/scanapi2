import { useCallback, useEffect, useState } from 'react'
import { api, HttpError, UNAUTHORIZED_EVENT } from '../api'
import type { Role } from '../types'

export type Session =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'offline' }
  | { status: 'signed-in'; role: Role }

export function useSession() {
  const [session, setSession] = useState<Session>({ status: 'loading' })

  const refresh = useCallback(async () => {
    try {
      const { role } = await api.me()
      setSession({ status: 'signed-in', role })
    } catch (e) {
      setSession({ status: e instanceof HttpError && e.status === 401 ? 'anonymous' : 'offline' })
    }
  }, [])

  useEffect(() => {
    void refresh()
    const onUnauthorized = () => setSession({ status: 'anonymous' })
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [refresh])

  const login = useCallback(async (password: string) => {
    const { role } = await api.login(password)
    setSession({ status: 'signed-in', role })
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setSession({ status: 'anonymous' })
    }
  }, [])

  return { session, refresh, login, logout }
}
