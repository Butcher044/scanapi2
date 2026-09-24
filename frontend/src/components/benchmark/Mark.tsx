import { Check, Minus } from 'lucide-react'
import type { BenchmarkCell } from '../../types'

/** "+" / "−" of one cell; a small dot marks a value set by hand instead of matched automatically. */
export default function Mark({ cell }: { cell: BenchmarkCell }) {
  const manual = cell.override !== null
  const label = `${cell.present ? 'есть' : 'нет'}${manual ? ', правка вручную' : ''}`
  return (
    <span className="relative inline-flex items-center justify-center w-7 h-7" aria-label={label} title={label}>
      {cell.present
        ? <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-[#86efac]/15 text-[#86efac]">
            <Check size={15} strokeWidth={2.75} />
          </span>
        : <Minus size={15} className="text-[#4A4A4A]" />}
      {manual && <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-[#fbbf24]" />}
    </span>
  )
}
