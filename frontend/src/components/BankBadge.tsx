const STYLES: Record<string, { dot: string; text: string }> = {
  tbank:    { dot: '#fbbf24', text: 'text-[#fbbf24]' },
  alfabank: { dot: '#f87171', text: 'text-[#f87171]' },
  sber:     { dot: '#86efac', text: 'text-[#86efac]' },
  tochka:   { dot: '#60a5fa', text: 'text-[#60a5fa]' },
}
const LABELS: Record<string, string> = {
  tbank: 'Т-Банк', alfabank: 'Альфа-Банк', sber: 'Сбер', tochka: 'Точка',
}

export default function BankBadge({ bank, label, size = 'md' }: { bank: string; label?: string; size?: 'sm' | 'md' }) {
  const s = STYLES[bank] ?? { dot: '#888', text: 'text-[#919191]' }
  const text = label ?? LABELS[bank] ?? bank
  const cls = size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full bg-[#1A1A1A] border border-[#333] font-medium ${cls} ${s.text}`}>
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: s.dot }} />
      {text}
    </span>
  )
}
