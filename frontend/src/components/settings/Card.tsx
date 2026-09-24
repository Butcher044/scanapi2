import type { ReactNode } from 'react'

export function Card({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="enter bg-[#0D0D0D] rounded-2xl p-6 flex flex-col gap-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-sm font-semibold tracking-widest text-[#E7E7E7]">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export const inputClass =
  'bg-black border border-[#333] rounded-xl px-3 py-2 text-sm text-white outline-none transition-colors focus:border-[#86efac]/60 [color-scheme:dark]'

export const primaryButton =
  'press inline-flex items-center justify-center gap-2 px-4 py-2 bg-[#86efac] text-black rounded-xl font-semibold text-sm hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed'

export const ghostButton =
  'press inline-flex items-center justify-center gap-1.5 px-3 py-1.5 border border-[#333] rounded-xl text-xs text-[#E7E7E7] hover:border-[#86efac]/40 disabled:opacity-50 disabled:cursor-not-allowed'
