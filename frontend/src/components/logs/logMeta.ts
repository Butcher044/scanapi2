import type { LogLevel } from '../../types'

export interface LevelMeta {
  /** Badge text; the level is always spelled out, never shown by color alone */
  label: string
  /** Badge colors, same scheme as the change badges */
  badgeClass: string
}

export const LEVELS: Record<LogLevel, LevelMeta> = {
  info:    { label: 'Инфо',     badgeClass: 'text-info bg-info-tint border-info/20' },
  success: { label: 'Успех',    badgeClass: 'text-ok bg-ok-tint border-ok/20' },
  warning: { label: 'Внимание', badgeClass: 'text-warn bg-warn-tint border-warn/20' },
  error:   { label: 'Ошибка',   badgeClass: 'text-danger bg-danger-tint border-danger/20' },
}

/** "27.09.2026 09:00:01" → "27.09 09:00:01": the year only adds noise in a 30-day log. */
export function shortTime(time: string): string {
  const [date, clock] = time.split(' ')
  if (!date || !clock) return time
  return `${date.slice(0, 5)} ${clock}`
}
