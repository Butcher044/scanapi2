import { useCallback, useEffect, useRef, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'theme'
const PAGE_COLOR: Record<Theme, string> = { light: '#f5f5f7', dark: '#0d0d0f' }

/* Matches the transition length of `.theme-fade` in index.css. */
const FADE_MS = 240

/**
 * Reads the stored choice. Light is the default: the user asked for a light
 * theme by default, so a dark OS setting does not override it. Storage can
 * throw in private mode, which is not an error worth surfacing — the default
 * is a correct answer.
 */
function readStoredTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme)
  const isFirstRun = useRef(true)
  const fadeTimer = useRef<number>()

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PAGE_COLOR[theme])

    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      /* Blocked storage: the theme still applies, it just will not persist. */
    }
  }, [theme])

  /* Cross-fade the repaint, but only on a real toggle — never on mount, where
     it would animate the whole page in from the wrong colors. */
  useEffect(() => {
    if (isFirstRun.current) {
      isFirstRun.current = false
      return
    }
    const root = document.documentElement
    root.classList.add('theme-fade')
    window.clearTimeout(fadeTimer.current)
    fadeTimer.current = window.setTimeout(() => root.classList.remove('theme-fade'), FADE_MS)
  }, [theme])

  useEffect(() => () => window.clearTimeout(fadeTimer.current), [])

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
  }, [])

  return { theme, toggleTheme }
}
