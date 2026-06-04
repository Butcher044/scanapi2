import { useEffect, useState } from 'react'
import { ChevronRight, ChevronDown, ExternalLink, Loader2, Search } from 'lucide-react'
import { api } from '../api'
import type { Service, Method } from '../types'
import HttpMethodBadge from '../components/HttpMethodBadge'

const BANKS = [
  { key: 'tbank',    label: 'Т-Банк',      color: '#fbbf24' },
  { key: 'alfabank', label: 'Альфа-Банк',   color: '#f87171' },
  { key: 'sber',     label: 'Сбер',         color: '#86efac' },
  { key: 'tochka',   label: 'Точка',        color: '#60a5fa' },
]

// ── JSON syntax highlighting ──────────────────────────────────────────────────
function colorizeJson(json: string): string {
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (m) => {
        let cls = 'text-[#7dd3fc]'        // number / bool / null
        if (/^"/.test(m)) {
          cls = /:$/.test(m) ? 'text-[#86efac]' : 'text-[#fbbf24]'  // key : value
        } else if (/true|false/.test(m)) {
          cls = 'text-[#f472b6]'
        } else if (/null/.test(m)) {
          cls = 'text-[#9ca3af]'
        }
        return `<span class="${cls}">${m}</span>`
      }
    )
}

function JsonBlock({ data, label }: { data: Record<string, unknown>; label: string }) {
  const [copied, setCopied] = useState(false)
  if (!data || Object.keys(data).length === 0) return null
  const text = JSON.stringify(data, null, 2)
  const html = colorizeJson(text)

  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-medium text-[#666] uppercase tracking-wider">{label}</span>
        <button
          onClick={copy}
          className="text-[10px] text-[#666] hover:text-[#86efac] transition-colors px-1.5 py-0.5 rounded border border-[#333] hover:border-[#86efac]/40"
        >
          {copied ? '✓ скопировано' : 'копировать'}
        </button>
      </div>
      <pre
        className="rounded-xl bg-[#0a0a0a] border border-[#1F1F1F] px-4 py-3 text-[11px] font-mono overflow-x-auto max-h-72 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  )
}

function MethodRow({ method }: { method: Method }) {
  const [open, setOpen] = useState(false)
  const hasExamples =
    Object.keys(method.request_example ?? {}).length > 0 ||
    Object.keys(method.response_example ?? {}).length > 0

  return (
    <div className="border-b border-[#1F1F1F] last:border-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-[#1F1F1F] transition-colors text-left"
      >
        <HttpMethodBadge method={method.http_method} size="sm" />
        <span className="font-mono text-xs text-[#E7E7E7] flex-1 truncate">
          {method.path || method.name}
        </span>
        {method.name && method.path && (
          <span className="text-xs text-[#666] truncate max-w-[160px] hidden lg:block">{method.name}</span>
        )}
        {hasExamples && (
          <span className="text-[9px] text-[#86efac]/60 bg-[#86efac]/10 px-1.5 py-0.5 rounded font-mono shrink-0">
            JSON
          </span>
        )}
        {method.url && (
          <a href={method.url} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="text-[#666] hover:text-[#86efac] shrink-0">
            <ExternalLink size={11} />
          </a>
        )}
        <ChevronDown size={12} className={`text-[#666] shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-4 pb-4 bg-black/30">
          {hasExamples ? (
            <>
              <JsonBlock data={method.request_example as Record<string, unknown>} label="Пример запроса" />
              <JsonBlock data={method.response_example as Record<string, unknown>} label="Пример ответа" />
            </>
          ) : (
            <p className="text-xs text-[#555] italic pt-2">JSON примеры недоступны</p>
          )}
        </div>
      )}
    </div>
  )
}

function ServiceRow({ service }: { service: Service }) {
  const [open, setOpen] = useState(false)
  const [methods, setMethods] = useState<Method[] | null>(null)
  const [loading, setLoading] = useState(false)

  const toggle = async () => {
    if (!open && !methods) {
      setLoading(true)
      const r = await api.methods(service.id).catch(() => ({ methods: [] }))
      setMethods(r.methods ?? [])
      setLoading(false)
    }
    setOpen(o => !o)
  }

  return (
    <div className="border border-[#1F1F1F] rounded-xl overflow-hidden mb-2">
      <button
        onClick={toggle}
        className="w-full flex items-center gap-3 px-4 py-3 bg-[#0D0D0D] hover:bg-[#1A1A1A] transition-colors text-left"
      >
        {open ? <ChevronDown size={14} className="text-[#919191]" /> : <ChevronRight size={14} className="text-[#919191]" />}
        <span className="text-sm font-medium text-[#E7E7E7] flex-1 truncate">{service.name}</span>
        {methods !== null && (
          <span className="text-[10px] text-[#666] bg-[#1F1F1F] px-2 py-0.5 rounded-full">
            {methods.length} методов
          </span>
        )}
        {loading && <Loader2 size={13} className="animate-spin text-[#666]" />}
      </button>
      {open && methods !== null && (
        <div className="bg-[#050505]">
          {methods.length === 0
            ? <p className="px-4 py-3 text-xs text-[#666]">Нет методов</p>
            : methods.map(m => <MethodRow key={m.id} method={m} />)
          }
        </div>
      )}
    </div>
  )
}

function BankView({ bankKey }: { bankKey: string }) {
  const [services, setServices] = useState<Service[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    setLoading(true); setServices(null)
    api.services(bankKey)
      .then(r => setServices(r.services ?? []))
      .catch(() => setServices([]))
      .finally(() => setLoading(false))
  }, [bankKey])

  const filtered = services?.filter(s => s.name.toLowerCase().includes(search.toLowerCase())) ?? []

  return (
    <div>
      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#666]" />
        <input
          className="w-full bg-[#1A1A1A] border border-[#333] rounded-xl pl-9 pr-4 py-2.5 text-sm text-[#E7E7E7] placeholder-[#666] focus:outline-none focus:border-[#86efac]/50 transition-colors"
          placeholder="Поиск сервисов…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-[#919191]">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Загрузка…</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-[#666] text-sm">
          {services?.length === 0 ? 'Нет данных — запустите парсер' : 'Ничего не найдено'}
        </div>
      ) : (
        <>
          <p className="text-xs text-[#666] mb-3">{filtered.length} сервисов</p>
          {filtered.map(s => <ServiceRow key={s.id} service={s} />)}
        </>
      )}
    </div>
  )
}

export default function Banks() {
  const [active, setActive] = useState('tbank')
  const bank = BANKS.find(b => b.key === active)!

  return (
    <div className="flex flex-col gap-6">
      {/* Bank tabs */}
      <div className="flex gap-3 flex-wrap">
        {BANKS.map(b => (
          <button
            key={b.key}
            onClick={() => setActive(b.key)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border transition-all ${
              active === b.key
                ? 'border-[#333] bg-[#1A1A1A] text-white'
                : 'border-[#1F1F1F] bg-[#0D0D0D] text-[#919191] hover:text-[#E7E7E7] hover:border-[#333]'
            }`}
          >
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: b.color }} />
            {b.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-[#0D0D0D] rounded-2xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <h2 className="text-xl font-medium text-white">API сервисы</h2>
          <div className="flex items-center gap-2 px-3 py-1 bg-[#1A1A1A] rounded-full border border-[#333]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: bank.color }} />
            <span className="text-xs font-medium text-white">{bank.label}</span>
          </div>
        </div>
        <BankView key={active} bankKey={active} />
      </div>
    </div>
  )
}
