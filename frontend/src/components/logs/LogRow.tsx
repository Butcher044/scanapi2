import { memo, useId, useState, type ReactNode } from 'react'
import type { LogEvent } from '../../types'
import { LEVELS, shortTime } from './logMeta'

function Line({ event, marker }: { event: LogEvent; marker: ReactNode }) {
  const level = LEVELS[event.level] ?? LEVELS.info
  return (
    <>
      <time className="shrink-0 text-console-dim" title={`${event.time} МСК`}>{shortTime(event.time)}</time>
      <span className={`w-[8ch] shrink-0 font-semibold ${level.tagClass}`}>{level.tag}</span>
      <span className="min-w-0 flex-1 break-words text-console-ink max-sm:basis-full">
        {event.message}
        {marker}
      </span>
    </>
  )
}

const ROW = 'flex w-full flex-wrap items-start gap-x-3 px-4 py-0.5 text-left'

/** One console line; a line with details is a button that unfolds them below. */
function LogRow({ event }: { event: LogEvent }) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()

  if (!event.details) {
    return <li className={ROW}><Line event={event} marker={null} /></li>
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-controls={detailsId}
        className={`${ROW} hover:bg-console-line/60 focus-visible:bg-console-line/60 focus-visible:outline-none`}
      >
        <Line
          event={event}
          marker={<span className="ml-2 text-console-dim">{open ? '[скрыть]' : '[подробнее]'}</span>}
        />
      </button>
      <pre
        id={detailsId}
        hidden={!open}
        className="mb-1 ml-4 mr-4 whitespace-pre-wrap break-words border-l-2 border-console-line py-1 pl-3 text-console-dim sm:ml-[calc(1rem+22ch+1.5rem)]"
      >
        {event.details}
      </pre>
    </li>
  )
}

/** Memoized: polling re-renders the list every few seconds, lines rarely change. */
export default memo(LogRow)
