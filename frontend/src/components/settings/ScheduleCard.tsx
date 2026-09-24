import { useState } from 'react'
import { Clock, Loader2 } from 'lucide-react'
import type { AppSettings } from '../../types'
import { Card, inputClass, primaryButton } from './Card'

interface Props {
  settings: AppSettings
  saving: boolean
  onSave: (time: string) => void
}

/** Remount with key={settings.scheduler_time} so the field follows the saved value. */
export default function ScheduleCard({ settings, saving, onSave }: Props) {
  const [time, setTime] = useState(settings.scheduler_time)
  const changed = time !== '' && time !== settings.scheduler_time

  return (
    <Card title="АВТОМАТИЧЕСКИЙ ПАРСИНГ">
      <form
        className="flex items-end gap-3 flex-wrap"
        onSubmit={e => { e.preventDefault(); if (changed) onSave(time) }}
      >
        <label className="flex flex-col gap-2">
          <span className="text-xs text-[#919191]">Каждый день в (МСК)</span>
          <input type="time" required disabled={saving} value={time} onChange={e => setTime(e.target.value)} className={inputClass} />
        </label>
        <button type="submit" disabled={!changed || saving} className={primaryButton}>
          {saving && <Loader2 size={13} className="animate-spin" />}
          Сохранить
        </button>
      </form>
      <p className="flex items-center gap-2 text-xs text-[#919191]">
        <Clock size={13} />
        Следующий запуск: <span className="text-[#E7E7E7]">{settings.next_run ?? '—'}</span>
      </p>
    </Card>
  )
}
