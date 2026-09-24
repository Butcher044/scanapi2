import { useCallback, useEffect, useState } from 'react'
import { api, errorText } from '../api'
import type { AppSettings, SettingsPatch } from '../types'
import { useMounted } from './useMounted'

export function useAppSettings() {
  const mounted = useMounted()
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api.settings()
      .then(s => { if (!cancelled) setSettings(s) })
      .catch(e => { if (!cancelled) setError(errorText(e, 'Не удалось загрузить настройки')) })
    return () => { cancelled = true }
  }, [loadAttempt])

  const reload = useCallback(() => setLoadAttempt(n => n + 1), [])

  const save = useCallback(async (patch: SettingsPatch): Promise<boolean> => {
    setSaving(true)
    setError(null)
    try {
      const saved = await api.saveSettings(patch)
      if (mounted.current) setSettings(saved)
      return true
    } catch (e) {
      if (mounted.current) setError(errorText(e, 'Не удалось сохранить настройки'))
      return false
    } finally {
      if (mounted.current) setSaving(false)
    }
  }, [mounted])

  return { settings, error, saving, reload, save }
}
