import type { HiddenBankSummary } from '../../types'
import { bankDotStyle } from '../../bankMeta'
import { HIDDEN_REASONS } from '../HiddenReasonBadge'

interface HiddenBankSummaryCardProps {
  bank: HiddenBankSummary
  active: boolean
  onSelect: () => void
}

export default function HiddenBankSummaryCard({ bank, active, onSelect }: HiddenBankSummaryCardProps) {

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={`flex flex-col gap-3 text-left px-4 py-3.5 rounded-xl border transition-colors ${
        active
          ? 'border-brand/30 bg-brand-tint'
          : 'border-line bg-surface hover:border-line-strong hover:bg-raised/60'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={bankDotStyle(bank.name)} />
          <span className="text-sm font-medium text-ink">{bank.label}</span>
        </div>
        <span className="text-lg font-bold text-ink tabular-nums">{bank.hidden_methods}</span>
      </div>

      <div className="flex items-center gap-3 text-xs text-ink-muted">
        <span>{bank.hidden_services} сервисов</span>
        <span>·</span>
        <span>{bank.hidden_methods} методов</span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {HIDDEN_REASONS.map(r => {
          const count = bank.by_reason[r.key] ?? 0
          if (count === 0) return null
          return (
            <span
              key={r.key}
              title={r.description}
              className="text-[10px] text-ink-muted bg-raised px-1.5 py-0.5 rounded"
            >
              {r.label}: {count}
            </span>
          )
        })}
      </div>
    </button>
  )
}
