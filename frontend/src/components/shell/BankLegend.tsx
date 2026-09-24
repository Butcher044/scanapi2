import { BANK_LABELS, BANK_ORDER, bankDotStyle } from '../../bankMeta'

/**
 * The standing legend for the bank colors. It is always present, so a bank's
 * identity is never carried by its color alone.
 */
export function BankLegend() {
  return (
    <ul className="flex flex-col gap-2.5">
      {BANK_ORDER.map((bank) => (
        <li key={bank} className="flex items-center gap-2.5">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
            style={bankDotStyle(bank)}
            aria-hidden
          />
          <span className="text-xs text-ink-muted">{BANK_LABELS[bank]}</span>
        </li>
      ))}
    </ul>
  )
}
