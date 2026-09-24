import { BankLegend } from './BankLegend'
import { NavList } from './NavList'
import type { NavItem } from './navItems'

type Props = {
  items: readonly NavItem[]
}

/** Desktop and tablet navigation. Phones get `MobileNav` instead. */
export function Sidebar({ items }: Props) {
  return (
    <aside className="sticky top-6 hidden h-[calc(100vh-3rem)] w-56 shrink-0 flex-col rounded-2xl border border-line bg-surface p-4 shadow-card md:flex lg:w-64">
      <NavList items={items} />

      <div className="mt-auto border-t border-line pt-4">
        <p className="mb-3 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
          Банки
        </p>
        <div className="px-3">
          <BankLegend />
        </div>
      </div>
    </aside>
  )
}
