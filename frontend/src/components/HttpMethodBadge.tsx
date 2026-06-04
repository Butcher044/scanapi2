const STYLES: Record<string, string> = {
  GET:    'text-[#86efac] bg-[#86efac]/10 border border-[#86efac]/20',
  POST:   'text-[#60a5fa] bg-[#60a5fa]/10 border border-[#60a5fa]/20',
  PUT:    'text-[#fbbf24] bg-[#fbbf24]/10 border border-[#fbbf24]/20',
  PATCH:  'text-[#fb923c] bg-[#fb923c]/10 border border-[#fb923c]/20',
  DELETE: 'text-[#f87171] bg-[#f87171]/10 border border-[#f87171]/20',
}

export default function HttpMethodBadge({ method, size = 'md' }: { method: string; size?: 'sm' | 'md' }) {
  const m = method.toUpperCase()
  const cls = STYLES[m] ?? 'text-[#919191] bg-[#1A1A1A]'
  const px = size === 'sm' ? 'px-1.5 py-0.5 text-[10px] min-w-[40px]' : 'px-2 py-0.5 text-xs min-w-[52px]'
  return (
    <span className={`inline-flex items-center justify-center rounded-lg font-mono font-bold ${px} ${cls}`}>
      {m}
    </span>
  )
}
