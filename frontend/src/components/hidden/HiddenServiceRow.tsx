import { useState } from 'react'
import { ChevronRight, ChevronDown, ExternalLink, Loader2 } from 'lucide-react'
import type { HiddenService } from '../../types'
import { useHiddenMethods } from '../../hooks/useHidden'
import { isSafeHttpUrl } from '../../safeUrl'
import HiddenMethodRow from './HiddenMethodRow'

export default function HiddenServiceRow({ service }: { service: HiddenService }) {
  const [open, setOpen] = useState(false)
  const { data: methods, error, loading, load } = useHiddenMethods(service.id)

  const toggle = () => {
    setOpen(o => !o)
    void load()  // no-op once loaded or while a request is in flight
  }

  return (
    <div className="border border-line rounded-xl overflow-hidden mb-2">
      <button
        type="button"
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
        {isSafeHttpUrl(service.url) && (
          <a href={service.url} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="text-ink-faint hover:text-brand shrink-0">
            <ExternalLink size={11} />
          </a>
        )}
        {loading && <Loader2 size={13} className="animate-spin text-ink-faint" />}
      </button>
      {open && (
        <div className="bg-page">
          {error && <p role="alert" className="px-4 py-3 text-xs text-danger">{error}</p>}
          {!error && methods !== null && (
            methods.length === 0
              ? <p className="px-4 py-3 text-xs text-ink-faint">Нет скрытых методов</p>
              : methods.map(m => <HiddenMethodRow key={m.id} method={m} />)
          )}
        </div>
      )}
    </div>
  )
}
