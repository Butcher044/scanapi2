import type { ReactNode } from 'react'
import type { LogCategory, LogLevel } from '../../types'
import type { LogFilters } from '../../hooks/useLogs'
import { CATEGORIES, CATEGORY_ORDER, LEVELS, LEVEL_ORDER } from './logMeta'

interface ChipProps {
  active: boolean
  onClick: () => void
  children: ReactNode
}

function Chip({ active, onClick, children }: ChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`press rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'border-brand/30 bg-brand-tint text-ink'
          : 'border-line bg-surface text-ink-muted hover:text-ink hover:border-line-strong'
      }`}
    >
      {children}
    </button>
  )
}

interface Props {
  filters: LogFilters
  onChange: (next: LogFilters) => void
}

export default function LogFilterBar({ filters, onChange }: Props) {
  const setLevel = (level: LogLevel | null) => onChange({ ...filters, level })
  const setCategory = (category: LogCategory | null) => onChange({ ...filters, category })

  return (
    <div className="flex flex-col gap-3">
      <div role="group" aria-label="Важность" className="flex flex-wrap items-center gap-2">
        <span className="w-24 shrink-0 text-xs text-ink-faint">Важность</span>
        <Chip active={filters.level === null} onClick={() => setLevel(null)}>Все</Chip>
        {LEVEL_ORDER.map(level => {
          const { icon: Icon, iconClass, filterLabel } = LEVELS[level]
          return (
            <Chip key={level} active={filters.level === level} onClick={() => setLevel(level)}>
              <span className="inline-flex items-center gap-1.5">
                <Icon size={12} className={iconClass} aria-hidden="true" />
                {filterLabel}
              </span>
            </Chip>
          )
        })}
      </div>
      <div role="group" aria-label="Раздел" className="flex flex-wrap items-center gap-2">
        <span className="w-24 shrink-0 text-xs text-ink-faint">Раздел</span>
        <Chip active={filters.category === null} onClick={() => setCategory(null)}>Все</Chip>
        {CATEGORY_ORDER.map(category => (
          <Chip key={category} active={filters.category === category} onClick={() => setCategory(category)}>
            {CATEGORIES[category]}
          </Chip>
        ))}
      </div>
    </div>
  )
}
