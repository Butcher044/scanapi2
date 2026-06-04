const STYLES = {
  added:    'text-[#86efac] bg-[#86efac]/10 border border-[#86efac]/20',
  removed:  'text-[#f87171] bg-[#f87171]/10 border border-[#f87171]/20',
  modified: 'text-[#fbbf24] bg-[#fbbf24]/10 border border-[#fbbf24]/20',
}
const LABELS = { added: '+ Добавлено', removed: '− Удалено', modified: '~ Изменено' }

export default function ActionBadge({ action }: { action: string }) {
  const key = action as keyof typeof STYLES
  return (
    <span className={`inline-flex items-center rounded-lg px-2 py-0.5 text-[11px] font-semibold ${STYLES[key] ?? 'text-[#919191] bg-[#1A1A1A]'}`}>
      {LABELS[key] ?? action}
    </span>
  )
}
