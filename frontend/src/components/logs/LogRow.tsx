import { memo, useId, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { LogEvent } from '../../types'
import { CATEGORIES, LEVELS } from './logMeta'

function LogRow({ event }: { event: LogEvent }) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()
  const level = LEVELS[event.level] ?? LEVELS.info
  const Icon = level.icon
  const clock = event.time.split(' ')[1] ?? event.time

  return (
    <li className="border-b border-line last:border-0">
      <div className="flex items-start gap-3 px-4 py-3">
        <Icon size={16} className={`mt-0.5 shrink-0 ${level.iconClass}`} aria-hidden="true" />
        <span className="sr-only">{level.label}:</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-ink break-words">{event.message}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-faint">
            <time className="font-mono tabular-nums" title={`${event.time} МСК`}>{clock}</time>
            <span className="rounded bg-raised px-1.5 py-0.5 text-ink-muted">
              {CATEGORIES[event.category] ?? event.category}
            </span>
            {event.details && (
              <button
                type="button"
                onClick={() => setOpen(o => !o)}
                aria-expanded={open}
                aria-controls={detailsId}
                className="press inline-flex items-center gap-1 text-ink-muted hover:text-ink transition-colors"
              >
                {open ? 'Скрыть подробности' : 'Подробнее'}
                <ChevronDown
                  size={12}
                  className={`transition-transform duration-200 ease-out ${open ? 'rotate-180' : ''}`}
                  aria-hidden="true"
                />
              </button>
            )}
          </div>
          {event.details && (
            <pre
              id={detailsId}
              hidden={!open}
              className="mt-2 max-h-80 overflow-auto rounded-xl border border-line bg-page p-3 font-mono text-xs text-ink-muted whitespace-pre-wrap break-words"
            >
              {event.details}
            </pre>
          )}
        </div>
      </div>
    </li>
  )
}

/** Memoized: polling re-renders the list every few seconds, rows rarely change. */
export default memo(LogRow)
