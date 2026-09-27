import type { ReactNode } from 'react'

export function Card({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="enter border border-line bg-surface shadow-card rounded-2xl p-6 flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-sm font-semibold tracking-widest text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export const inputClass =
  'bg-page border border-line rounded-xl px-3 py-2 text-sm text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-line-strong'

export const primaryButton =
  'press inline-flex items-center justify-center gap-2 px-4 py-2 bg-brand-solid text-brand-fg rounded-xl font-semibold text-sm hover:brightness-110 disabled:opacity-50 disabled:cursor-not-allowed'

export const ghostButton =
  'press inline-flex items-center justify-center gap-1.5 px-3 py-1.5 border border-line-strong rounded-xl text-xs text-ink hover:bg-raised disabled:opacity-50 disabled:cursor-not-allowed'
