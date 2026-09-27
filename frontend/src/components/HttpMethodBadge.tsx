const STYLES: Record<string, string> = {
  GET:    'text-ok bg-ok-tint border border-ok/25',
  POST:   'text-info bg-info-tint border border-info/25',
  PUT:    'text-warn bg-warn-tint border border-warn/25',
  PATCH:  'text-orange bg-orange-tint border border-orange/25',
  DELETE: 'text-danger bg-danger-tint border border-danger/25',
}

export default function HttpMethodBadge({ method, size = 'md' }: { method: string; size?: 'sm' | 'md' }) {
  const m = method.toUpperCase()
  const cls = STYLES[m] ?? 'text-ink-muted bg-raised'
  const px = size === 'sm' ? 'px-1.5 py-0.5 text-[10px] min-w-[40px]' : 'px-2 py-0.5 text-xs min-w-[52px]'
  return (
    <span className={`inline-flex items-center justify-center rounded-lg font-mono font-bold ${px} ${cls}`}>
      {m}
    </span>
  )
}
