import { useEffect, useState } from 'react'
import { ChevronRight, ChevronDown, ExternalLink, Loader2, Search } from 'lucide-react'
import { api } from '../api'
import type { Service, Method } from '../types'
import HttpMethodBadge from '../components/HttpMethodBadge'
import JsonBlock, { hasBody } from '../components/JsonBlock'
import { isSafeHttpUrl } from '../safeUrl'
import { bankDotStyle } from '../bankMeta'

const BANKS = [
  { key: 'tbank',    label: 'Т-Банк' },
  { key: 'alfabank', label: 'Альфа-Банк' },
  { key: 'sber',     label: 'Сбер' },
  { key: 'tochka',   label: 'Точка' },
]

function MethodRow({ method }: { method: Method }) {
  const [open, setOpen] = useState(false)
  const hasExamples =
    Object.keys(method.request_example ?? {}).length > 0 ||
    Object.keys(method.response_example ?? {}).length > 0

  return (
    <div className="border-b border-line last:border-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-raised transition-colors text-left"
      >
        <HttpMethodBadge method={method.http_method} size="sm" />
        <span className="font-mono text-xs text-ink flex-1 truncate">
          {method.path || method.name}
        </span>
        {method.name && method.path && (
          <span className="text-xs text-ink-faint truncate max-w-[160px] hidden lg:block">{method.name}</span>
        )}
        {hasExamples && (
          <span className="text-[9px] text-ok bg-ok-tint px-1.5 py-0.5 rounded font-mono shrink-0">
            JSON
          </span>
        )}
        {isSafeHttpUrl(method.url) && (
          <a href={method.url} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="text-ink-faint hover:text-brand shrink-0">
            <ExternalLink size={11} />
          </a>
        )}
        <ChevronDown size={12} className={`text-ink-faint shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-4 pb-4 bg-page">
          {hasExamples ? (
            <>
              <JsonBlock data={method.request_example} label="Пример запроса" />
              <JsonBlock data={method.response_example} label="Пример ответа" />
            </>
          ) : (
            <p className="text-xs text-ink-faint italic pt-2">JSON примеры недоступны</p>
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
    <div className="border border-line rounded-xl overflow-hidden mb-2">
      <button
        onClick={toggle}
        className="w-full flex items-center gap-3 px-4 py-3 bg-surface hover:bg-raised transition-colors text-left"
      >
        {open ? <ChevronDown size={14} className="text-ink-muted" /> : <ChevronRight size={14} className="text-ink-muted" />}
        <span className="text-sm font-medium text-ink flex-1 truncate">{service.name}</span>
        {methods !== null && (
          <span className="text-[10px] text-ink-faint bg-raised px-2 py-0.5 rounded-full">
            {methods.length} методов
          </span>
        )}
        {loading && <Loader2 size={13} className="animate-spin text-ink-faint" />}
      </button>
      {open && methods !== null && (
        <div className="bg-page">
          {methods.length === 0
            ? <p className="px-4 py-3 text-xs text-ink-faint">Нет методов</p>
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
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
        <input
          className="w-full bg-surface border border-line rounded-xl pl-9 pr-4 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:outline-none focus:border-line-strong transition-colors"
          placeholder="Поиск сервисов…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-ink-muted">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Загрузка…</span>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-ink-faint text-sm">
          {services?.length === 0 ? 'Нет данных — запустите парсер' : 'Ничего не найдено'}
        </div>
      ) : (
        <>
          <p className="text-xs text-ink-faint mb-3">{filtered.length} сервисов</p>
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
            aria-pressed={active === b.key}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border transition-colors ${
              active === b.key
                ? 'border-brand/30 bg-brand-tint text-ink'
                : 'border-line bg-surface text-ink-muted hover:text-ink hover:border-line-strong'
            }`}
          >
            <span className="w-2 h-2 rounded-full shrink-0" style={bankDotStyle(b.key)} />
            {b.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="border border-line bg-surface shadow-card rounded-2xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <h2 className="text-xl font-medium text-ink">API сервисы</h2>
          <div className="flex items-center gap-2 px-3 py-1 bg-raised rounded-full border border-line-strong">
            <span className="w-2 h-2 rounded-full" style={bankDotStyle(bank.key)} />
            <span className="text-xs font-medium text-ink">{bank.label}</span>
          </div>
        </div>
        <BankView key={active} bankKey={active} />
      </div>
    </div>
  )
}
