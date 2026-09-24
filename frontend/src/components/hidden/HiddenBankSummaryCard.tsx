import type { HiddenBankSummary } from '../../types'
import { BANK_COLORS } from '../../bankMeta'
import { HIDDEN_REASONS } from '../HiddenReasonBadge'

interface HiddenBankSummaryCardProps {
  bank: HiddenBankSummary
  active: boolean
  onSelect: () => void
}

export default function HiddenBankSummaryCard({ bank, active, onSelect }: HiddenBankSummaryCardProps) {
  const color = BANK_COLORS[bank.name] ?? '#888'

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex flex-col gap-3 text-left px-4 py-3.5 rounded-xl border transition-all ${
        active
          ? 'border-[#333] bg-[#1A1A1A]'
          : 'border-[#1F1F1F] bg-[#0D0D0D] hover:border-[#333] hover:bg-[#1A1A1A]/60'
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <span className="text-sm font-medium text-white">{bank.label}</span>
        </div>
        <span className="text-lg font-bold text-white tabular-nums">{bank.hidden_methods}</span>
      </div>

      <div className="flex items-center gap-3 text-xs text-[#919191]">
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
              className="text-[10px] text-[#919191] bg-[#1F1F1F] px-1.5 py-0.5 rounded"
            >
              {r.label}: {count}
            </span>
          )
        })}
      </div>
    </button>
  )
}
