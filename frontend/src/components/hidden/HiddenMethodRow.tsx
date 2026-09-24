import { useState } from 'react'
import { ChevronDown, ExternalLink } from 'lucide-react'
import type { HiddenMethod } from '../../types'
import { isSafeHttpUrl } from '../../safeUrl'
import HttpMethodBadge from '../HttpMethodBadge'
import HiddenReasonBadge from '../HiddenReasonBadge'
import JsonBlock, { hasBody } from '../JsonBlock'

export default function HiddenMethodRow({ method }: { method: HiddenMethod }) {
  const [open, setOpen] = useState(false)
  const hasExamples = hasBody(method.request_example) || hasBody(method.response_example)

  return (
    <div className="border-b border-[#1F1F1F] last:border-0">
      <button
        type="button"
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
        <HiddenReasonBadge reason={method.hidden_reason} />
        {isSafeHttpUrl(method.url) && (
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
              <JsonBlock data={method.request_example} label="Пример запроса" />
              <JsonBlock data={method.response_example} label="Пример ответа" />
            </>
          ) : (
            <p className="text-xs text-[#555] italic pt-2">JSON примеры недоступны</p>
          )}
        </div>
      )}
    </div>
  )
}
