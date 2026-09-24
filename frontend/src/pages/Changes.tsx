import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { ExternalLink, ChevronDown, ChevronLeft, ChevronRight, Loader2, Filter, ArrowUp, ArrowDown } from 'lucide-react'
import { api } from '../api'
import type { Change } from '../types'
import { isSafeHttpUrl } from '../safeUrl'
import BankBadge from '../components/BankBadge'
import ActionBadge from '../components/ActionBadge'
import TypeBadge from '../components/TypeBadge'

const BANKS   = [{ v: '', l: 'Все банки' }, { v: 'tbank', l: 'Т-Банк' }, { v: 'alfabank', l: 'Альфа-Банк' }, { v: 'sber', l: 'Сбер' }, { v: 'tochka', l: 'Точка' }]
const TYPES   = [{ v: '', l: 'Все типы' }, { v: 'service', l: 'Сервис' }, { v: 'method', l: 'Метод' }, { v: 'field', l: 'Поле' }]
const ACTIONS = [{ v: '', l: 'Все действия' }, { v: 'added', l: 'Добавлено' }, { v: 'removed', l: 'Удалено' }, { v: 'modified', l: 'Изменено' }]

const PAGE_SIZE = 50

function DiffChips({ old: oldV, new: newV }: { old: string; new: string }) {
  if (!oldV && !newV) return null
  const items = [
    ...(oldV ? oldV.split(',').map(v => ({ t: 'old', v: v.trim() })) : []),
    ...(newV ? newV.split(',').map(v => ({ t: 'new', v: v.trim() })) : []),
  ]
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {items.map((p, i) => (
        <span key={i} className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
          p.t === 'new' ? 'bg-[#86efac]/10 text-[#86efac]' : 'bg-[#f87171]/10 text-[#f87171]'
        }`}>{p.v}</span>
      ))}
    </div>
  )
}

function ChangeRow({ change, isFirst }: { change: Change; isFirst: boolean }) {
  const [open, setOpen] = useState(false)
  const hasDiff = !!(change.old_value || change.new_value)

  return (
    <>
      <tr
        className={`transition-colors border-b border-transparent last:border-0 ${
          isFirst ? 'bg-[#1A1A1A]' : 'hover:bg-[#1A1A1A]'
        } ${hasDiff ? 'cursor-pointer' : ''}`}
        onClick={() => hasDiff && setOpen(o => !o)}
      >
        <td className="py-3 pl-2 rounded-l-xl"><BankBadge bank={change.bank} label={change.bank_label} /></td>
        <td className="py-3"><TypeBadge type={change.type} /></td>
        <td className="py-3"><ActionBadge action={change.action} /></td>
        <td className="py-3 max-w-xs">
          <span className="font-mono text-xs text-white truncate block" title={change.entity}>{change.entity}</span>
        </td>
        <td className="py-3 text-right text-[#919191] text-xs whitespace-nowrap">{change.detected_at}</td>
        <td className="py-3 text-right pr-2 rounded-r-xl">
          <div className="flex items-center justify-end gap-2">
            {change.action === 'added' && <ArrowUp className="h-4 w-4 text-[#86efac]" />}
            {change.action === 'removed' && <ArrowDown className="h-4 w-4 text-[#f87171]" />}
            {isSafeHttpUrl(change.url) && (
              <a href={change.url} target="_blank" rel="noopener noreferrer"
                onClick={e => e.stopPropagation()}
                className="text-[#666] hover:text-[#E7E7E7]">
                <ExternalLink size={13} />
              </a>
            )}
            {hasDiff && (
              <button type="button" aria-expanded={open} aria-label="Показать изменения в полях"
                onClick={e => { e.stopPropagation(); setOpen(o => !o) }}
                className="text-[#666] hover:text-[#E7E7E7]">
                <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
              </button>
            )}
          </div>
        </td>
      </tr>
      {open && hasDiff && (
        <tr className="bg-black/40 border-b border-transparent">
          <td colSpan={6} className="px-4 py-3">
            <div className="text-xs text-[#666] mb-1">Изменения в полях:</div>
            <DiffChips old={change.old_value} new={change.new_value} />
          </td>
        </tr>
      )}
    </>
  )
}

const selClass = "bg-[#1A1A1A] border border-[#333] rounded-xl px-3 py-2 text-sm text-[#E7E7E7] focus:outline-none focus:border-[#86efac]/50 transition-colors cursor-pointer"

export default function Changes() {
  const { refresh } = useOutletContext<{ refresh: number }>()
  const [changes, setChanges] = useState<Change[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fb, setFb] = useState('')
  const [ft, setFt] = useState('')
  const [fa, setFa] = useState('')

  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false  // ignore responses of superseded requests (fast filter/page changes)
    setLoading(true)
    api.changes({ bank: fb, type: ft, action: fa, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then(r => {
        if (cancelled) return
        const lastPage = Math.max(0, Math.ceil(r.total / PAGE_SIZE) - 1)
        if (page > lastPage) { setPage(lastPage); return }  // list shrank (e.g. after cleanup)
        setChanges(r.changes)
        setTotal(r.total)
        setError(false)
      })
      .catch(() => { if (!cancelled) setError(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [fb, ft, fa, page, refresh])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="flex flex-col gap-4">
      {/* Filters */}
      <div className="bg-[#0D0D0D] rounded-2xl p-5">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2 text-[#919191] text-sm">
            <Filter size={14} />
            <span>Фильтры</span>
          </div>
          <select aria-label="Банк" className={selClass} value={fb} onChange={e => { setPage(0); setFb(e.target.value) }}>
            {BANKS.map(b => <option key={b.v} value={b.v}>{b.l}</option>)}
          </select>
          <select aria-label="Тип" className={selClass} value={ft} onChange={e => { setPage(0); setFt(e.target.value) }}>
            {TYPES.map(t => <option key={t.v} value={t.v}>{t.l}</option>)}
          </select>
          <select aria-label="Действие" className={selClass} value={fa} onChange={e => { setPage(0); setFa(e.target.value) }}>
            {ACTIONS.map(a => <option key={a.v} value={a.v}>{a.l}</option>)}
          </select>
          <span className="ml-auto text-xs text-[#666]">{total.toLocaleString('ru')} записей</span>
        </div>
      </div>

      {/* Table */}
      <div className="bg-[#0D0D0D] rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#919191] border-b border-[#1F1F1F]">
                <th className="px-4 py-4 text-left font-medium pl-5">Банк</th>
                <th className="px-4 py-4 text-left font-medium">Тип</th>
                <th className="px-4 py-4 text-left font-medium">Действие</th>
                <th className="px-4 py-4 text-left font-medium">Сущность</th>
                <th className="px-4 py-4 text-right font-medium">Дата</th>
                <th className="px-4 py-4 pr-5" />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={6} className="py-16 text-center">
                  <div className="flex items-center justify-center gap-2 text-[#919191]">
                    <Loader2 size={16} className="animate-spin" />
                    <span className="text-sm">Загрузка…</span>
                  </div>
                </td></tr>
              ) : error ? (
                <tr><td colSpan={6} className="py-16 text-center text-[#f87171] text-sm">
                  Не удалось загрузить изменения
                </td></tr>
              ) : changes.length === 0 ? (
                <tr><td colSpan={6} className="py-16 text-center text-[#666] text-sm">
                  Нет изменений по выбранным фильтрам
                </td></tr>
              ) : (
                changes.map((c, i) => <ChangeRow key={c.id} change={c} isFirst={i === 0} />)
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="px-5 py-4 border-t border-[#1F1F1F] flex items-center justify-between">
            <span className="text-xs text-[#666]">Страница {page + 1} из {totalPages}</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setPage(p => p - 1)} disabled={page === 0} aria-label="Предыдущая страница"
                className="p-2 text-[#919191] hover:text-white disabled:opacity-30 hover:bg-[#1A1A1A] rounded-lg transition-colors">
                <ChevronLeft size={15} />
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                const p = Math.max(0, Math.min(page - 3, totalPages - 7)) + i
                return (
                  <button key={p} onClick={() => setPage(p)} aria-current={p === page ? 'page' : undefined} aria-label={`Страница ${p + 1}`}
                    className={`w-8 h-8 rounded-lg text-xs font-medium transition-colors ${
                      p === page ? 'bg-[#86efac] text-black' : 'text-[#919191] hover:text-white hover:bg-[#1A1A1A]'
                    }`}>{p + 1}</button>
                )
              })}
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1} aria-label="Следующая страница"
                className="p-2 text-[#919191] hover:text-white disabled:opacity-30 hover:bg-[#1A1A1A] rounded-lg transition-colors">
                <ChevronRight size={15} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
