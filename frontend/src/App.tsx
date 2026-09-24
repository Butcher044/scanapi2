import { Suspense, lazy, useCallback, useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { Loader2, RotateCw, X } from 'lucide-react'
import ParsePanel from './components/ParsePanel'
import { AppHeader } from './components/shell/AppHeader'
import { MobileNav } from './components/shell/MobileNav'
import { Sidebar } from './components/shell/Sidebar'
import { navItemsFor } from './components/shell/navItems'
import { useParse } from './hooks/useParse'
import { useSession } from './hooks/useSession'
import { useTheme } from './hooks/useTheme'
import Overview from './pages/Overview'
import Login from './pages/Login'
import type { Role } from './types'

/* Overview is the landing route and stays in the main bundle. The rest are
   split out, so a first paint does not carry pages the viewer may never open. */
const Banks = lazy(() => import('./pages/Banks'))
const Changes = lazy(() => import('./pages/Changes'))
const Benchmark = lazy(() => import('./pages/Benchmark'))
const Settings = lazy(() => import('./pages/Settings'))
const HiddenServices = lazy(() => import('./pages/HiddenServices'))

interface LayoutProps {
  role: Role
  onLogout: () => void
}

function RouteFallback() {
  return (
    <div className="flex min-h-64 items-center justify-center">
      <Loader2 className="animate-spin text-ink-faint" aria-label="Загрузка" />
    </div>
  )
}

function Layout({ role, onLogout }: LayoutProps) {
  const [refresh, setRefresh] = useState(0)
  const [showPanel, setShowPanel] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const { theme, toggleTheme } = useTheme()

  const bumpRefresh = useCallback(() => setRefresh((n) => n + 1), [])
  const { status: parseStatus, error: parseError, starting, start, clearError } = useParse(bumpRefresh)
  const isRunning = parseStatus?.running ?? false

  const closeMenu = useCallback(() => setMenuOpen(false), [])
  const openMenu = useCallback(() => setMenuOpen(true), [])
  const openPanel = useCallback(() => setShowPanel(true), [])

  const triggerParse = useCallback(async () => {
    if (isRunning || starting) return
    if (await start()) setShowPanel(true)
  }, [isRunning, starting, start])

  const items = navItemsFor(role)

  return (
    <div className="min-h-screen bg-page text-ink">
      <AppHeader
        role={role}
        theme={theme}
        isParsing={isRunning}
        isStarting={starting}
        onToggleTheme={toggleTheme}
        onOpenMenu={openMenu}
        onOpenParsePanel={openPanel}
        onParse={() => void triggerParse()}
        onLogout={onLogout}
      />

      <MobileNav items={items} open={menuOpen} onClose={closeMenu} />

      <main className="mx-auto flex w-full max-w-[1600px] gap-6 px-4 py-6 sm:px-6">
        <Sidebar items={items} />

        <div className="flex min-w-0 flex-1 flex-col gap-6">
          <Suspense fallback={<RouteFallback />}>
            <Outlet context={{ refresh, role }} />
          </Suspense>

          <div className="mt-auto flex items-center justify-end gap-2 pt-2">
            <span
              className={`h-2 w-2 rounded-full ${isRunning ? 'bg-warn' : 'bg-ok'}`}
              aria-hidden
            />
            <span className="text-xs text-ink-muted">{isRunning ? 'Парсинг' : 'Онлайн'}</span>
          </div>
        </div>
      </main>

      {parseError && (
        <div
          role="alert"
          className="enter fixed bottom-4 left-4 right-4 z-40 flex items-center gap-3 rounded-xl border border-danger/40 bg-surface px-4 py-3 shadow-pop sm:right-auto sm:max-w-md"
        >
          <span className="flex-1 text-sm text-danger">{parseError}</span>
          <button
            type="button"
            onClick={clearError}
            aria-label="Закрыть"
            className="press shrink-0 text-ink-faint hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {showPanel && parseStatus && (
        <ParsePanel status={parseStatus} onClose={() => setShowPanel(false)} />
      )}
    </div>
  )
}

function FullScreen({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 bg-page text-sm text-ink-muted">
      {children}
    </div>
  )
}

export default function App() {
  const { session, refresh, login, logout } = useSession()

  if (session.status === 'loading') {
    return (
      <FullScreen>
        <Loader2 className="animate-spin text-brand" aria-label="Загрузка" />
      </FullScreen>
    )
  }

  if (session.status === 'offline') {
    return (
      <FullScreen>
        <span>Сервер недоступен</span>
        <button
          type="button"
          onClick={() => void refresh()}
          className="press flex items-center gap-2 rounded-lg border border-line bg-surface px-4 py-2 text-ink hover:border-line-strong"
        >
          <RotateCw size={14} aria-hidden /> Повторить
        </button>
      </FullScreen>
    )
  }

  if (session.status === 'anonymous') return <Login onLogin={login} />

  const isAdmin = session.role === 'admin'

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout role={session.role} onLogout={() => void logout()} />}>
          <Route index element={<Overview />} />
          <Route path="banks" element={<Banks />} />
          <Route path="changes" element={<Changes />} />
          <Route path="benchmark" element={<Benchmark />} />
          <Route path="hidden" element={isAdmin ? <HiddenServices /> : <Navigate to="/" replace />} />
          <Route path="settings" element={isAdmin ? <Settings /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
