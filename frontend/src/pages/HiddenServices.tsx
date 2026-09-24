import { useEffect, useState } from 'react'
import { Loader2, RotateCw, Search, EyeOff } from 'lucide-react'
import { useHiddenSummary, useHiddenServices } from '../hooks/useHidden'
import HiddenBankSummaryCard from '../components/hidden/HiddenBankSummaryCard'
import HiddenServiceRow from '../components/hidden/HiddenServiceRow'

function HiddenBankView({ bank }: { bank: string }) {
  const { data: services, error, loading } = useHiddenServices(bank)
  const [search, setSearch] = useState('')

  const filtered = services?.filter(s => s.name.toLowerCase().includes(search.toLowerCase())) ?? []

  return (
    <div>
      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#666]" />
        <input
          className="w-full bg-[#1A1A1A] border border-[#333] rounded-xl pl-9 pr-4 py-2.5 text-sm text-[#E7E7E7] placeholder-[#666] focus:outline-none focus:border-[#86efac]/50 transition-colors"
          placeholder="Поиск скрытых сервисов…"
          aria-label="Поиск скрытых сервисов"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>
      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-[#919191]">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Загрузка…</span>
        </div>
      ) : error ? (
        <div role="alert" className="text-center py-16 text-[#f87171] text-sm">{error}</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-[#666] text-sm">
          {services?.length === 0 ? 'скрытых сервисов нет' : 'Ничего не найдено'}
        </div>
      ) : (
        <>
          <p className="text-xs text-[#666] mb-3">{filtered.length} сервисов</p>
          {filtered.map(s => <HiddenServiceRow key={s.id} service={s} />)}
        </>
      )}
    </div>
  )
}

export default function HiddenServices() {
  const { data: summary, error, loading, reload } = useHiddenSummary()
  const [active, setActive] = useState<string | null>(null)

  // Keep the selection valid: a bank whose last hidden method disappeared is no
  // longer in the summary, and the panel below would silently render nothing.
  useEffect(() => {
    if (!summary) return
    setActive(prev =>
      prev && summary.banks.some(b => b.name === prev) ? prev : summary.banks[0]?.name ?? null
    )
  }, [summary])

  const activeBank = summary?.banks.find(b => b.name === active) ?? null

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <EyeOff className="h-5 w-5 text-[#919191]" />
        <h1 className="text-2xl font-bold tracking-wide">Скрытые сервисы</h1>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-[#919191]">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Загрузка…</span>
        </div>
      ) : error ? (
        <div className="flex items-center gap-3 flex-wrap px-5 py-3 bg-[#0D0D0D] border border-[#f87171]/40 rounded-2xl">
          <span role="alert" className="text-sm text-[#f87171]">{error}</span>
          <button
            type="button"
            onClick={reload}
            className="press flex items-center gap-2 px-3 py-1.5 border border-[#333] rounded-xl text-xs text-[#E7E7E7] hover:border-[#86efac]/40"
          >
            <RotateCw size={12} /> Повторить
          </button>
        </div>
      ) : !summary || summary.banks.length === 0 ? (
        <div className="text-center py-16 text-[#666] text-sm bg-[#0D0D0D] rounded-2xl">скрытых сервисов нет</div>
      ) : (
        <>
          {/* Per-bank summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {summary.banks.map(b => (
              <HiddenBankSummaryCard
                key={b.name}
                bank={b}
                active={b.name === active}
                onSelect={() => setActive(b.name)}
              />
            ))}
          </div>

          {/* Selected bank's hidden services → methods */}
          {activeBank && (
            <div className="bg-[#0D0D0D] rounded-2xl p-6">
              <div className="flex items-center gap-3 mb-5">
                <h2 className="text-xl font-medium text-white">Скрытые API сервисы</h2>
                <div className="flex items-center gap-2 px-3 py-1 bg-[#1A1A1A] rounded-full border border-[#333]">
                  <span className="text-xs font-medium text-white">{activeBank.label}</span>
                </div>
              </div>
              <HiddenBankView key={activeBank.name} bank={activeBank.name} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
