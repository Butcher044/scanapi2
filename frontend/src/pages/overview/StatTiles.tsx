import { Wallet } from 'lucide-react'
import type { Summary } from '../../types'

type Props = {
  summary: Summary | null
}

type Tile = { label: string; value: number; isDelta: boolean }

function tilesFor(summary: Summary | null): Tile[] {
  return [
    { label: 'Банков', value: summary?.banks.length ?? 0, isDelta: false },
    { label: 'Сервисов', value: summary?.total_services ?? 0, isDelta: false },
    { label: 'Изм. сегодня', value: summary?.changes_today ?? 0, isDelta: true },
    { label: 'Изм. за неделю', value: summary?.changes_week ?? 0, isDelta: true },
  ]
}

export function StatTiles({ summary }: Props) {
  return (
    <section className="flex flex-col justify-between gap-8 rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6 xl:flex-row xl:items-center">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-ink-muted">
          <Wallet className="h-5 w-5" aria-hidden />
          <span className="text-sm sm:text-base">Всего эндпоинтов</span>
        </div>
        <div className="text-4xl font-bold tracking-tight text-ink tabular-nums sm:text-5xl">
          {(summary?.total_methods ?? 0).toLocaleString('ru')}
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4 sm:gap-8 xl:gap-14">
        {tilesFor(summary).map(({ label, value, isDelta }) => {
          const positive = isDelta && value > 0
          return (
            <div key={label} className="flex flex-col gap-1">
              <dt className="text-xs text-ink-muted sm:text-sm">{label}</dt>
              <dd
                className={[
                  'text-xl font-semibold tabular-nums sm:text-2xl',
                  positive ? 'text-ok' : 'text-ink',
                ].join(' ')}
              >
                {positive ? `+${value}` : value}
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}
