import type { BenchmarkCell } from '../../types'

const OPTIONS: { value: boolean | null; label: string }[] = [
  { value: null,  label: 'Авто' },
  { value: true,  label: 'Есть' },
  { value: false, label: 'Нет'  },
]

interface Props {
  cell: BenchmarkCell
  saving: boolean
  onChange: (present: boolean | null) => void
}

/** Admin-only segmented control: automatic matching, or force "+" / "−". */
export default function OverrideControl({ cell, saving, onChange }: Props) {
  return (
    <div role="group" aria-label="Значение ячейки" aria-busy={saving}
      className="inline-flex p-0.5 bg-black border border-[#333] rounded-lg">
      {OPTIONS.map(({ value, label }) => {
        const active = cell.override === value
        return (
          <button
            key={label}
            type="button"
            aria-pressed={active}
            disabled={saving}
            onClick={() => { if (!active) onChange(value) }}
            className={`press px-2 py-0.5 rounded-md text-[11px] disabled:opacity-50 ${
              active ? 'bg-[#262626] text-[#E7E7E7]' : 'text-[#919191] hover:text-[#E7E7E7]'
            }`}
          >
            {value === null ? `${label} (${cell.auto ? '+' : '−'})` : label}
          </button>
        )
      })}
    </div>
  )
}
