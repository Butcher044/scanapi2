import type { Change } from '../types'

const LABELS: Record<Change['type'], string> = {
  service: 'Сервис',
  method: 'Метод',
  field: 'Поле',
}

/**
 * Deliberately neutral. The label already names the type, and three more hues
 * here would compete with the bank colors that do carry meaning.
 */
export default function TypeBadge({ type }: { type: Change['type'] }) {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-lg border border-line bg-raised px-2 py-0.5 text-[11px] font-medium text-ink-muted">
      {LABELS[type] ?? type}
    </span>
  )
}
