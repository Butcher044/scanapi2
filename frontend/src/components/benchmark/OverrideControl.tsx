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
      className="inline-flex p-0.5 bg-raised border border-line rounded-lg">
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
              active ? 'bg-surface text-ink shadow-card' : 'text-ink-muted hover:text-ink'
            }`}
          >
            {value === null ? `${label} (${cell.auto ? '+' : '−'})` : label}
          </button>
        )
      })}
    </div>
  )
}
