import { memo, useId, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import type { LogEvent } from '../../types'
import { LEVELS, shortTime } from './logMeta'

/** One log line: time, level badge, message; details unfold below on demand. */
function LogRow({ event }: { event: LogEvent }) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()
  const level = LEVELS[event.level] ?? LEVELS.info

  return (
    <li className="border-b border-line/70 px-4 py-2.5 last:border-0 hover:bg-raised transition-colors">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <time
          className="w-[7.5rem] shrink-0 pt-px font-mono text-[11px] tabular-nums leading-5 text-ink-faint"
          title={`${event.time} МСК`}
        >
          {shortTime(event.time)}
        </time>
        <span
          className={`inline-flex w-[4.75rem] shrink-0 justify-center rounded-md border py-0.5 text-[10px] font-semibold uppercase tracking-wide ${level.badgeClass}`}
        >
          {level.label}
        </span>
        <p className="min-w-0 flex-1 break-words text-[13px] leading-5 text-ink max-sm:basis-full">
          {event.message}
        </p>
        {event.details && (
          <button
            type="button"
            onClick={() => setOpen(o => !o)}
            aria-expanded={open}
            aria-controls={detailsId}
            className="press ml-auto inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 text-xs leading-5 text-ink-muted hover:text-ink transition-colors"
          >
            {open ? 'Скрыть' : 'Подробнее'}
            <ChevronDown
              size={12}
              aria-hidden="true"
              className={`transition-transform duration-200 ease-out ${open ? 'rotate-180' : ''}`}
            />
          </button>
        )}
      </div>
      {event.details && (
        <pre
          id={detailsId}
          hidden={!open}
          className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-page p-3 font-mono text-xs leading-relaxed text-ink-muted sm:ml-[calc(7.5rem+4.75rem+1.5rem)]"
        >
          {event.details}
        </pre>
      )}
    </li>
  )
}

/** Memoized: polling re-renders the list every few seconds, lines rarely change. */
export default memo(LogRow)
