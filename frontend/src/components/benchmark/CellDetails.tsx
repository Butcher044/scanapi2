import type { BenchmarkCell } from '../../types'
import OverrideControl from './OverrideControl'

interface Props {
  cell: BenchmarkCell
  isAdmin: boolean
  saving: boolean
  onOverride: (present: boolean | null) => void
}

function methodsText(matched: number, total: number, byName: boolean): string {
  if (total === 0) return 'без методов'
  if (byName) return `все ${total} мет.`
  return `${matched} из ${total} мет.`
}

/** What produced the cell: matched services of one bank, plus the admin override control. */
export default function CellDetails({ cell, isAdmin, saving, onOverride }: Props) {
  return (
    <div className="flex flex-col gap-2 min-w-0">
      {cell.evidence.length === 0 ? (
        <span className="text-xs text-[#666]">Совпадений нет</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {cell.evidence.map(e => (
            <li key={e.service} className="flex flex-col text-xs leading-snug">
              <span className="text-[#E7E7E7] break-words">{e.service}</span>
              <span className="text-[#666]">
                {methodsText(e.matched, e.total, e.by_name)}{e.by_name ? ' · по названию' : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
      {isAdmin && <OverrideControl cell={cell} saving={saving} onChange={onOverride} />}
    </div>
  )
}
