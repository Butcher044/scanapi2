import { AlertTriangle, CheckCircle2, Info, XCircle, type LucideIcon } from 'lucide-react'
import type { LogCategory, LogLevel } from '../../types'

export interface LevelMeta {
  label: string
  /** Filter chip label (plural) */
  filterLabel: string
  icon: LucideIcon
  /** Icon color; the level is always shipped with a text label too, never color alone */
  iconClass: string
}

export const LEVELS: Record<LogLevel, LevelMeta> = {
  error:   { label: 'Ошибка',         filterLabel: 'Ошибки',         icon: XCircle,       iconClass: 'text-danger' },
  warning: { label: 'Предупреждение', filterLabel: 'Предупреждения', icon: AlertTriangle, iconClass: 'text-warn' },
  success: { label: 'Успешно',        filterLabel: 'Успешные',       icon: CheckCircle2,  iconClass: 'text-ok' },
  info:    { label: 'Информация',     filterLabel: 'Информация',     icon: Info,          iconClass: 'text-ink-faint' },
}

export const LEVEL_ORDER: readonly LogLevel[] = ['error', 'warning', 'success', 'info']

export const CATEGORIES: Record<LogCategory, string> = {
  parser:   'Парсинг',
  schedule: 'Расписание',
  telegram: 'Telegram',
  proxy:    'Прокси',
  settings: 'Настройки',
  system:   'Система',
}

export const CATEGORY_ORDER = Object.keys(CATEGORIES) as LogCategory[]

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

/** Moscow calendar date (YYYY-MM-DD) of `now`, to compare with the server's `date`. */
function moscowDate(now: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow' }).format(now)
}

/** "Сегодня", "Вчера" or "27 сентября 2026" for a YYYY-MM-DD Moscow date. */
export function dayTitle(date: string, now: Date = new Date()): string {
  const today = moscowDate(now)
  const yesterday = moscowDate(new Date(now.getTime() - 86_400_000))
  if (date === today) return 'Сегодня'
  if (date === yesterday) return 'Вчера'
  const [y, m, d] = date.split('-').map(Number)
  return `${d} ${MONTHS[m - 1] ?? ''} ${y}`
}
