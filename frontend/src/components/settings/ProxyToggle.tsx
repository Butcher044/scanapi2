import { AlertTriangle } from 'lucide-react'
import { Card } from './Card'

interface Props {
  enabled: boolean
  saving: boolean
  /** null while the proxy list is still loading */
  usableCount: number | null
  onChange: (enabled: boolean) => void
}

export default function ProxyToggle({ enabled, saving, usableCount, onChange }: Props) {
  return (
    <Card title="ПАРСИНГ ЧЕРЕЗ ПРОКСИ">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-[#919191] max-w-xl">
          Каждый запрос к банку идёт через следующий прокси по кругу. Если прокси не отвечает, берётся
          следующий; если не работает ни один, запрос идёт напрямую.
        </p>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label="Парсинг через прокси"
          disabled={saving}
          onClick={() => onChange(!enabled)}
          className={`press relative w-11 h-6 shrink-0 rounded-full disabled:opacity-50 ${enabled ? 'bg-[#86efac]' : 'bg-[#333]'}`}
        >
          <span
            className={`absolute top-1 left-1 w-4 h-4 rounded-full transition-transform duration-200 ease-out ${
              enabled ? 'translate-x-5 bg-black' : 'translate-x-0 bg-[#919191]'
            }`}
          />
        </button>
      </div>
      {enabled && usableCount === 0 && (
        <p role="status" className="flex items-center gap-2 text-xs text-[#fbbf24]">
          <AlertTriangle size={13} />
          Нет действующих прокси, поэтому парсинг пойдёт напрямую.
        </p>
      )}
    </Card>
  )
}
