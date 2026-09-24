import { useState, type FormEvent } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { errorText } from '../../api'
import type { NewProxy } from '../../types'
import { inputClass, primaryButton } from './Card'

const DEFAULT_DAYS = 30
const MAX_DAYS = 3650
type ExpiryMode = 'days' | 'date'

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function AddProxyForm({ onAdd }: { onAdd: (proxy: NewProxy) => Promise<void> }) {
  const [url, setUrl] = useState('')
  const [label, setLabel] = useState('')
  const [mode, setMode] = useState<ExpiryMode>('days')
  const [days, setDays] = useState(String(DEFAULT_DAYS))
  const [date, setDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    const dayCount = Number(days)
    if (mode === 'days' && !(Number.isInteger(dayCount) && dayCount >= 1 && dayCount <= MAX_DAYS)) {
      setError(`Срок: целое число дней от 1 до ${MAX_DAYS}`)
      return
    }
    if (mode === 'date' && !date) {
      setError('Укажите дату окончания')
      return
    }
    const expiry = mode === 'days' ? { days: dayCount } : { expires_on: date }
    setBusy(true)
    setError(null)
    try {
      await onAdd({ url: url.trim(), label: label.trim(), ...expiry })
      setUrl('')
      setLabel('')
    } catch (err) {
      setError(errorText(err, 'Не удалось добавить прокси'))
    } finally {
      setBusy(false)
    }
  }

  const modeButton = (value: ExpiryMode, text: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      onClick={() => setMode(value)}
      className={`press px-3 py-1.5 rounded-lg text-xs ${mode === value ? 'bg-[#1F1F1F] text-white' : 'text-[#919191] hover:text-[#E7E7E7]'}`}
    >
      {text}
    </button>
  )

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 pt-5 border-t border-[#1F1F1F]">
      <div className="flex gap-3 flex-wrap items-end">
        <label className="flex flex-col gap-2 flex-[2_1_18rem]">
          <span className="text-xs text-[#919191]">Адрес (http:// или socks5://)</span>
          <input
            required
            value={url}
            maxLength={500}
            spellCheck={false}
            autoComplete="off"
            placeholder="socks5://user:pass@1.2.3.4:1080"
            onChange={e => setUrl(e.target.value)}
            className={`${inputClass} font-mono`}
          />
        </label>
        <label className="flex flex-col gap-2 flex-[1_1_10rem]">
          <span className="text-xs text-[#919191]">Метка</span>
          <input value={label} maxLength={100} placeholder="необязательно" onChange={e => setLabel(e.target.value)} className={inputClass} />
        </label>
      </div>

      <div className="flex gap-3 flex-wrap items-end">
        <div className="flex flex-col gap-2">
          <span className="text-xs text-[#919191]">Срок действия</span>
          <div className="flex items-center gap-2">
            <div className="flex p-1 bg-black border border-[#333] rounded-xl" role="group" aria-label="Как указать срок">
              {modeButton('days', 'Дней')}
              {modeButton('date', 'До даты')}
            </div>
            {mode === 'days' ? (
              <input
                type="number" required min={1} max={MAX_DAYS} value={days}
                aria-label="Количество дней"
                onChange={e => setDays(e.target.value)}
                className={`${inputClass} w-24`}
              />
            ) : (
              <input
                type="date" required min={todayIso()} value={date}
                aria-label="Дата окончания"
                onChange={e => setDate(e.target.value)}
                className={inputClass}
              />
            )}
          </div>
        </div>
        <button type="submit" disabled={busy || !url.trim()} className={primaryButton}>
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} strokeWidth={2.5} />}
          Добавить
        </button>
      </div>

      {error && <p role="alert" className="text-xs text-[#f87171]">{error}</p>}
    </form>
  )
}
