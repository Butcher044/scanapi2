import { BANK_COLORS } from '../../bankMeta'
import type { BenchmarkBank } from '../../types'
import { Card } from '../settings/Card'

interface Props {
  banks: BenchmarkBank[]
  unmatched: Record<string, string[]>
}

/** Services that fit no benchmark row: unique products, or a hint that the catalog needs a new row. */
export default function UnmatchedCard({ banks, unmatched }: Props) {
  const total = banks.reduce((n, b) => n + (unmatched[b.key]?.length ?? 0), 0)
  return (
    <Card title={`НЕ ПОПАЛИ В ТАБЛИЦУ · ${total}`}>
      <p className="text-xs text-[#919191] -mt-2">
        Сервисы, которые не подошли ни под одну строку: уникальные продукты банка или кандидаты в новые строки.
      </p>
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {banks.map(b => {
          const names = unmatched[b.key] ?? []
          return (
            <div key={b.key} className="flex flex-col gap-2 min-w-0">
              <span className="flex items-center gap-2 text-xs font-medium text-[#E7E7E7]">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: BANK_COLORS[b.key] }} />
                {b.label}
                <span className="text-[#666] tabular-nums">{names.length}</span>
              </span>
              {names.length === 0
                ? <span className="text-xs text-[#666]">—</span>
                : (
                  <ul className="flex flex-col gap-1">
                    {names.map(name => <li key={name} className="text-xs text-[#919191] break-words">{name}</li>)}
                  </ul>
                )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}
