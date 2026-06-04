const STYLES = {
  service: 'text-[#60a5fa] bg-[#60a5fa]/10',
  method:  'text-[#c084fc] bg-[#c084fc]/10',
  field:   'text-[#fb923c] bg-[#fb923c]/10',
}
const LABELS = { service: 'Сервис', method: 'Метод', field: 'Поле' }

export default function TypeBadge({ type }: { type: string }) {
  const key = type as keyof typeof STYLES
  return (
    <span className={`inline-flex items-center rounded-lg px-2 py-0.5 text-[11px] font-medium ${STYLES[key] ?? 'text-[#919191] bg-[#1A1A1A]'}`}>
      {LABELS[key] ?? type}
    </span>
  )
}
