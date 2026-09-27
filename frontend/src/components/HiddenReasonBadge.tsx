/**
 * Why a method/service is kept in the DB but hidden from the public dashboard.
 * The backend enum has exactly these four values — anything else (a future
 * value, a typo, bad data) falls back to a neutral style instead of crashing.
 */
import type { HiddenReason } from '../types'

export interface HiddenReasonInfo {
  key: HiddenReason
  label: string
  description: string
}

export const HIDDEN_REASONS: HiddenReasonInfo[] = [
  { key: 'private', label: 'Закрытое пространство', description: 'Партнёрское или внутреннее пространство портала, недоступное публично' },
  { key: 'superseded', label: 'Устаревшая версия', description: 'Статья устарела — на портале есть более новая версия' },
  { key: 'not_in_menu', label: 'Нет в меню', description: 'Спецификация есть, но страницы в навигации портала нет' },
  { key: 'ghost', label: 'Призрак из ленты', description: 'Упомянут только в ленте обновлений, путь на портале нерабочий' },
]

const STYLES: Record<HiddenReason, string> = {
  private: 'text-danger bg-danger-tint',
  superseded: 'text-warn bg-warn-tint',
  not_in_menu: 'text-violet bg-violet-tint',
  ghost: 'text-ink-muted bg-raised',
}

const FALLBACK_STYLE = 'text-ink-muted bg-raised'
const FALLBACK_DESCRIPTION = 'Причина скрытия неизвестна'

export default function HiddenReasonBadge({ reason }: { reason: string }) {
  const info = HIDDEN_REASONS.find(r => r.key === reason)
  // reason comes from the API as a plain string: an unknown key is styled neutrally
  const cls = STYLES[reason as HiddenReason] ?? FALLBACK_STYLE
  const label = info?.label ?? reason
  const title = info?.description ?? FALLBACK_DESCRIPTION

  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-lg px-2 py-0.5 text-[11px] font-medium ${cls}`}
    >
      {label}
    </span>
  )
}
