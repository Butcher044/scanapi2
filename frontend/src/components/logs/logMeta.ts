import type { LogLevel } from '../../types'

export interface LevelMeta {
  /** Console tag; the level is always spelled out, never shown by color alone */
  tag: string
  /** Tag color on the console background */
  tagClass: string
}

export const LEVELS: Record<LogLevel, LevelMeta> = {
  info:    { tag: 'ИНФО',     tagClass: 'text-console-info' },
  success: { tag: 'УСПЕХ',    tagClass: 'text-console-ok' },
  warning: { tag: 'ВНИМАНИЕ', tagClass: 'text-console-warn' },
  error:   { tag: 'ОШИБКА',   tagClass: 'text-console-err' },
}

/** "27.09.2026 09:00:01" → "27.09 09:00:01": the year only adds noise in a 30-day log. */
export function shortTime(time: string): string {
  const [date, clock] = time.split(' ')
  if (!date || !clock) return time
  return `${date.slice(0, 5)} ${clock}`
}
