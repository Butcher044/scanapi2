import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { AlfaLogo } from '../AlfaLogo'
import { BankLegend } from './BankLegend'
import { NavList } from './NavList'
import type { NavItem } from './navItems'

type Props = {
  items: readonly NavItem[]
  open: boolean
  onClose: () => void
}

/**
 * Phone navigation. Below `md` the sidebar is hidden, so without this there is
 * no way to reach any page but the one already open.
 *
 * The panel stays mounted and is moved with a transform, which keeps the
 * transition interruptible — a quick open/close does not restart from zero the
 * way a keyframe animation would.
 */
export function MobileNav({ items, open, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement>(null)

  /* Keep the closed drawer out of the tab order and away from screen readers. */
  useEffect(() => {
    const panel = panelRef.current
    if (!panel) return
    if (open) panel.removeAttribute('inert')
    else panel.setAttribute('inert', '')
  }, [open])

  useEffect(() => {
    if (!open) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  return (
    <div className="md:hidden">
      <div
        onClick={onClose}
        aria-hidden
        className={[
          'fixed inset-0 z-40 bg-ink/40 backdrop-blur-[2px] transition-opacity duration-[240ms] ease-out',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        ].join(' ')}
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Навигация"
        className={[
          'fixed inset-y-0 left-0 z-50 flex w-[17rem] max-w-[82vw] flex-col',
          'border-r border-line bg-surface shadow-pop',
          'transition-transform duration-[240ms] ease-out will-change-transform',
          open ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <div className="flex items-center gap-2.5">
            <AlfaLogo size={26} className="rounded-md" />
            <span className="text-sm font-bold tracking-tight text-ink">API Monitor</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть меню"
            className="press grid h-9 w-9 place-items-center rounded-lg text-ink-muted hover:bg-raised hover:text-ink"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3">
          <NavList items={items} onNavigate={onClose} />
        </div>

        <div className="border-t border-line p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
            Банки
          </p>
          <BankLegend />
        </div>
      </div>
    </div>
  )
}
