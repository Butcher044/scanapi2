import type { Change } from '../types'

const STYLES: Record<Change['action'], string> = {
  added: 'text-ok bg-ok-tint border-ok/25',
  removed: 'text-danger bg-danger-tint border-danger/25',
  modified: 'text-warn bg-warn-tint border-warn/25',
}

const LABELS: Record<Change['action'], string> = {
  added: '+ Добавлено',
  removed: '− Удалено',
  modified: '~ Изменено',
}

export default function ActionBadge({ action }: { action: Change['action'] }) {
  const style = STYLES[action] ?? 'text-ink-muted bg-raised border-line'

  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-lg border px-2 py-0.5 text-[11px] font-semibold ${style}`}
    >
      {LABELS[action] ?? action}
    </span>
  )
}
