import { bankDotStyle, bankLabel } from '../bankMeta'

type Props = {
  bank: string
  label?: string
  size?: 'sm' | 'md'
}

/**
 * The chip itself stays neutral and the dot carries the bank's hue, so the name
 * is readable at full text contrast instead of in a series color.
 */
export default function BankBadge({ bank, label, size = 'md' }: Props) {
  const sizing = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'

  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-raised font-medium text-ink ${sizing}`}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={bankDotStyle(bank)}
      />
      {label ?? bankLabel(bank)}
    </span>
  )
}
