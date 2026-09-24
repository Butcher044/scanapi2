import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, Trash2 } from 'lucide-react'
import type { Proxy } from '../../types'
import { ghostButton } from './Card'

const CONFIRM_MS = 5000
const WARN_DAYS = 3

function ExpiryBadge({ daysLeft }: { daysLeft: number | null }) {
  if (daysLeft === null) return <span className="text-xs text-[#666]">бессрочно</span>
  if (daysLeft < 0) return <span className="text-xs px-2 py-0.5 rounded-md bg-[#f87171]/10 text-[#f87171]">истёк</span>
  const tone = daysLeft < WARN_DAYS ? 'bg-[#fbbf24]/10 text-[#fbbf24]' : 'bg-[#1A1A1A] text-[#919191]'
  return <span className={`text-xs px-2 py-0.5 rounded-md ${tone}`}>{daysLeft} дн.</span>
}

function StatusDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? 'bg-[#444]' : ok ? 'bg-[#86efac]' : 'bg-[#f87171]'
  const label = ok === null ? 'не проверялся' : ok ? 'работает' : 'не работает'
  return <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} role="img" aria-label={label} title={label} />
}

function LastCheck({ proxy }: { proxy: Proxy }) {
  if (!proxy.last_checked_at) return <span className="text-[#666]">не проверялся</span>
  if (!proxy.last_ok) {
    return <span className="text-[#f87171]">{proxy.last_checked_at} · {proxy.last_error ?? 'ошибка'}</span>
  }
  const latency = proxy.last_latency_ms !== null ? `${proxy.last_latency_ms} мс` : null
  const parts = [proxy.last_checked_at, proxy.last_country, proxy.last_ip, latency]
  return <span className="text-[#919191]">{parts.filter(Boolean).join(' · ')}</span>
}

interface Props {
  proxy: Proxy
  checking: boolean
  deleting: boolean
  onCheck: (id: number) => void
  onDelete: (id: number) => void
}

export default function ProxyRow({ proxy, checking, deleting, onCheck, onDelete }: Props) {
  const [confirming, setConfirming] = useState(false)

  // Two-step delete: the second click within 5 s confirms
  useEffect(() => {
    if (!confirming) return
    const t = setTimeout(() => setConfirming(false), CONFIRM_MS)
    return () => clearTimeout(t)
  }, [confirming])

  const confirm = () => {
    if (confirming) onDelete(proxy.id)
    setConfirming(!confirming)
  }

  return (
    <li className="flex items-center gap-4 py-3 border-b border-[#1F1F1F] last:border-0 flex-wrap">
      <StatusDot ok={proxy.last_ok} />
      <div className="flex-1 min-w-[12rem] flex flex-col gap-1">
        <span className="font-mono text-xs text-white break-all">{proxy.url}</span>
        <span className="text-[11px]">
          {proxy.label && <span className="text-[#E7E7E7]">{proxy.label} · </span>}
          <LastCheck proxy={proxy} />
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-[#666]">
        {proxy.expires_at && <span>до {proxy.expires_at}</span>}
        <ExpiryBadge daysLeft={proxy.days_left} />
      </div>
      <div className="flex items-center gap-2">
        <button type="button" className={ghostButton} disabled={checking || deleting} onClick={() => onCheck(proxy.id)}>
          {checking ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Проверить
        </button>
        <button
          type="button"
          aria-live="polite"
          disabled={deleting}
          className={`${ghostButton} ${confirming ? 'border-[#f87171]/60 text-[#f87171]' : ''}`}
          onClick={confirm}
        >
          {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
          {confirming ? 'Точно удалить?' : 'Удалить'}
        </button>
      </div>
    </li>
  )
}
