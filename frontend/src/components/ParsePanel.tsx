import { Loader2, CheckCircle, XCircle, Clock, X } from 'lucide-react'
import type { BankParseStatus, ParseStatus } from '../types'
import { BANK_COLORS, BANK_LABELS } from '../bankMeta'

function StatusIcon({ status }: { status: BankParseStatus['status'] }) {
  if (status === 'running') return <Loader2 size={14} className="animate-spin text-[#86efac]" />
  if (status === 'done')    return <CheckCircle size={14} className="text-[#86efac]" />
  if (status === 'error')   return <XCircle size={14} className="text-[#f87171]" />
  return <Clock size={14} className="text-[#666]" />
}

function BankStatusRow({ bank, st }: { bank: string; st: BankParseStatus }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1F1F1F] last:border-0">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: BANK_COLORS[bank] ?? '#888' }} />
        <span className={`text-sm ${st.status === 'pending' ? 'text-[#666]' : 'text-[#E7E7E7]'}`}>
          {BANK_LABELS[bank] ?? bank}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {st.status === 'done' && (
          <span className="text-[10px] text-[#666]">
            {st.services} сервисов · {st.methods.toLocaleString('ru')} методов · {st.changes} изм.
          </span>
        )}
        {st.status === 'error' && (
          <span className="text-[10px] text-[#f87171] max-w-[120px] truncate" title={st.error ?? ''}>Ошибка</span>
        )}
        {st.status === 'running' && (
          <span className="text-[10px] text-[#86efac]">Парсинг…</span>
        )}
        <StatusIcon status={st.status} />
      </div>
    </div>
  )
}

export default function ParsePanel({ status, onClose }: { status: ParseStatus; onClose: () => void }) {
  const banks = Object.keys(status.banks)
  const done = banks.filter(b => status.banks[b].status === 'done').length
  const errors = banks.filter(b => status.banks[b].status === 'error').length
  const total = banks.length

  return (
    <div role="status" aria-live="polite" className="fixed bottom-6 right-6 bg-[#0D0D0D] border border-[#333] rounded-2xl p-5 w-80 shadow-2xl z-50">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {status.running
            ? <Loader2 size={14} className="animate-spin text-[#86efac]" />
            : errors > 0
              ? <XCircle size={14} className="text-[#f87171]" />
              : <CheckCircle size={14} className="text-[#86efac]" />}
          <span className="text-sm font-semibold text-white">
            {status.running ? 'Парсинг API банков…' : `Готово: ${done}/${total}`}
          </span>
        </div>
        {!status.running && (
          <button onClick={onClose} aria-label="Закрыть" className="text-[#666] hover:text-[#E7E7E7] transition-colors">
            <X size={15} />
          </button>
        )}
      </div>

      <div role="progressbar" aria-label="Прогресс парсинга" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done + errors}
        className="h-1 bg-[#1A1A1A] rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-[#86efac] rounded-full transition-all duration-500"
          style={{ width: `${total > 0 ? ((done + errors) / total) * 100 : 0}%` }}
        />
      </div>

      <div>
        {banks.map(bank => (
          <BankStatusRow key={bank} bank={bank} st={status.banks[bank]} />
        ))}
      </div>

      {!status.running && status.finished_at && (
        <p className="mt-3 text-[10px] text-[#666] text-right">
          Завершено: {status.finished_at}
        </p>
      )}
    </div>
  )
}
