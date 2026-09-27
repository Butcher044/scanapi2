import { Loader2, CheckCircle, XCircle, Clock, X } from 'lucide-react'
import type { BankParseStatus, ParseStatus } from '../types'
import { BANK_LABELS, bankDotStyle } from '../bankMeta'

function StatusIcon({ status }: { status: BankParseStatus['status'] }) {
  if (status === 'running') return <Loader2 size={14} className="animate-spin text-brand" />
  if (status === 'done')    return <CheckCircle size={14} className="text-ok" />
  if (status === 'error')   return <XCircle size={14} className="text-danger" />
  return <Clock size={14} className="text-ink-faint" />
}

function BankStatusRow({ bank, st }: { bank: string; st: BankParseStatus }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-line last:border-0">
      <div className="flex items-center gap-2 shrink-0">
        <span className="w-2 h-2 rounded-full shrink-0" style={bankDotStyle(bank)} />
        <span className={`text-sm whitespace-nowrap ${st.status === 'pending' ? 'text-ink-faint' : 'text-ink'}`}>
          {BANK_LABELS[bank] ?? bank}
        </span>
      </div>
      <div className="flex items-center gap-2 min-w-0">
        {st.status === 'done' && (
          <span className="text-[10px] text-ink-faint text-right">
            {st.services} сервисов · {st.methods.toLocaleString('ru')} методов · {st.changes} изм.
          </span>
        )}
        {st.status === 'error' && (
          <span className="text-[10px] text-danger max-w-[120px] truncate" title={st.error ?? ''}>Ошибка</span>
        )}
        {st.status === 'running' && (
          <span className="text-[10px] text-ink-muted">Парсинг…</span>
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
    <div role="status" aria-live="polite" className="fixed bottom-6 right-6 bg-surface border border-line rounded-2xl p-5 w-80 shadow-pop z-50">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {status.running
            ? <Loader2 size={14} className="animate-spin text-brand" />
            : errors > 0
              ? <XCircle size={14} className="text-danger" />
              : <CheckCircle size={14} className="text-ok" />}
          <span className="text-sm font-semibold text-ink">
            {status.running ? 'Парсинг API банков…' : `Готово: ${done}/${total}`}
          </span>
        </div>
        {!status.running && (
          <button onClick={onClose} aria-label="Закрыть" className="text-ink-faint hover:text-ink transition-colors">
            <X size={15} />
          </button>
        )}
      </div>

      <div role="progressbar" aria-label="Прогресс парсинга" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done + errors}
        className="h-1 bg-raised rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-brand rounded-full transition-all duration-500"
          style={{ width: `${total > 0 ? ((done + errors) / total) * 100 : 0}%` }}
        />
      </div>

      <div>
        {banks.map(bank => (
          <BankStatusRow key={bank} bank={bank} st={status.banks[bank]} />
        ))}
      </div>

      {!status.running && status.finished_at && (
        <p className="mt-3 text-[10px] text-ink-faint text-right">
          Завершено: {status.finished_at}
        </p>
      )}
    </div>
  )
}
