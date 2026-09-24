import { useState } from 'react'

/**
 * Shared JSON viewer for request/response bodies coming from bank portals.
 * A body is not always an object: the parsers also produce top-level arrays
 * and (rarely) bare scalars, so `data` is `unknown` and emptiness is decided
 * by hasBody() rather than by Object.keys().
 */

/** True when a parsed body is worth rendering (`{}` and `[]` are not). */
export function hasBody(data: unknown): boolean {
  if (data === null || data === undefined) return false
  if (Array.isArray(data)) return data.length > 0
  if (typeof data === 'object') return Object.keys(data as object).length > 0
  if (typeof data === 'string') return data.trim() !== ''
  return true  // number | boolean
}

// ── JSON syntax highlighting ──────────────────────────────────────────────────
// Escaping happens before any <span> is added, so portal-supplied content
// cannot inject markup into the highlighted output.
export function colorizeJson(json: string): string {
  return json
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (m) => {
        let cls = 'text-[#7dd3fc]'        // number / bool / null
        if (/^"/.test(m)) {
          cls = /:$/.test(m) ? 'text-[#86efac]' : 'text-[#fbbf24]'  // key : value
        } else if (/true|false/.test(m)) {
          cls = 'text-[#f472b6]'
        } else if (/null/.test(m)) {
          cls = 'text-[#9ca3af]'
        }
        return `<span class="${cls}">${m}</span>`
      }
    )
}

export default function JsonBlock({ data, label }: { data: unknown; label: string }) {
  const [copied, setCopied] = useState(false)
  if (!hasBody(data)) return null
  const text = JSON.stringify(data, null, 2)
  const html = colorizeJson(text)

  const copy = () => {
    navigator.clipboard.writeText(text)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => setCopied(false))  // clipboard denied — silently keep the label unchanged
  }

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-medium text-[#666] uppercase tracking-wider">{label}</span>
        <button
          type="button"
          onClick={copy}
          className="text-[10px] text-[#666] hover:text-[#86efac] transition-colors px-1.5 py-0.5 rounded border border-[#333] hover:border-[#86efac]/40"
        >
          {copied ? '✓ скопировано' : 'копировать'}
        </button>
      </div>
      <pre
        className="rounded-xl bg-[#0a0a0a] border border-[#1F1F1F] px-4 py-3 text-[11px] font-mono overflow-x-auto max-h-72 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  )
}
