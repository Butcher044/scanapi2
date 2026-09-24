import { Loader2, LogOut, Menu, Play } from 'lucide-react'
import { AlfaLogo } from '../AlfaLogo'
import { ThemeToggle } from '../ThemeToggle'
import { ROLE_LABELS } from './navItems'
import type { Theme } from '../../hooks/useTheme'
import type { Role } from '../../types'

type Props = {
  role: Role
  theme: Theme
  isParsing: boolean
  isStarting: boolean
  onToggleTheme: () => void
  onOpenMenu: () => void
  onOpenParsePanel: () => void
  onParse: () => void
  onLogout: () => void
}

export function AppHeader({
  role,
  theme,
  isParsing,
  isStarting,
  onToggleTheme,
  onOpenMenu,
  onOpenParsePanel,
  onParse,
  onLogout,
}: Props) {
  const isAdmin = role === 'admin'
  const parseDisabled = isParsing || isStarting

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-page/85 backdrop-blur-xl">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label="Открыть меню"
          className="press grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line text-ink-muted hover:bg-raised hover:text-ink md:hidden"
        >
          <Menu size={18} />
        </button>

        <div className="flex min-w-0 items-center gap-2.5">
          <AlfaLogo size={30} className="shrink-0 rounded-lg" />
          <span className="truncate text-[15px] font-bold tracking-tight text-ink">
            API Monitor
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
          {isParsing && (
            <button
              type="button"
              onClick={onOpenParsePanel}
              className="press hidden items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 hover:border-line-strong sm:flex"
            >
              <Loader2 size={13} className="animate-spin text-brand" aria-hidden />
              <span className="text-xs font-medium text-ink-muted">Идёт парсинг…</span>
            </button>
          )}

          {isAdmin && (
            <button
              type="button"
              onClick={onParse}
              disabled={parseDisabled}
              className="press flex items-center gap-2 rounded-lg bg-brand-solid px-3 py-2 text-sm font-semibold text-brand-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
            >
              {parseDisabled ? (
                <Loader2 size={14} className="animate-spin" aria-hidden />
              ) : (
                <Play size={14} strokeWidth={2.5} aria-hidden />
              )}
              <span className="hidden sm:inline">Парсинг</span>
              <span className="sr-only sm:hidden">Запустить парсинг</span>
            </button>
          )}

          <ThemeToggle theme={theme} onToggle={onToggleTheme} />

          <span className="hidden text-xs text-ink-muted lg:inline">{ROLE_LABELS[role]}</span>

          <button
            type="button"
            onClick={onLogout}
            aria-label="Выйти"
            title="Выйти"
            className="press grid h-9 w-9 place-items-center rounded-lg border border-line text-ink-muted hover:bg-raised hover:text-ink"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </header>
  )
}
