import { NavLink } from 'react-router-dom'
import type { NavItem } from './navItems'

type Props = {
  items: readonly NavItem[]
  onNavigate?: () => void
}

export function NavList({ items, onNavigate }: Props) {
  return (
    <nav className="flex flex-col gap-1">
      {items.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            [
              'press flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm',
              isActive
                ? 'bg-brand-tint font-semibold text-brand'
                : 'font-medium text-ink-muted hover:bg-raised hover:text-ink',
            ].join(' ')
          }
        >
          <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
          <span className="truncate">{label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
