import { Fragment } from 'react'
import { ChevronRight } from 'lucide-react'
import { BANK_COLORS } from '../../bankMeta'
import { cellId } from '../../hooks/useBenchmark'
import type { BenchmarkBank, BenchmarkRow } from '../../types'
import CellDetails from './CellDetails'
import Mark from './Mark'

export interface BenchmarkGroup {
  title: string
  rows: BenchmarkRow[]
}

interface Props {
  banks: BenchmarkBank[]
  groups: BenchmarkGroup[]
  totals: Record<string, number>
  expanded: ReadonlySet<string>
  isAdmin: boolean
  saving: ReadonlySet<string>
  onToggle: (key: string) => void
  onOverride: (capability: string, bank: string, present: boolean | null) => void
}

export default function BenchmarkTable({
  banks, groups, totals, expanded, isAdmin, saving, onToggle, onOverride,
}: Props) {
  const columns = banks.length + 1
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] border-separate border-spacing-0 text-sm">
        <thead>
          <tr>
            <th scope="col" className="text-left font-medium text-xs tracking-widest text-[#919191] pb-4 pr-4">
              ВОЗМОЖНОСТЬ
            </th>
            {banks.map(b => (
              <th key={b.key} scope="col" className="pb-4 px-2 w-[18%] font-medium align-bottom">
                <div className="flex flex-col items-center gap-1">
                  <span className="flex items-center gap-2 text-[#E7E7E7]">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: BANK_COLORS[b.key] }} />
                    {b.label}
                  </span>
                  <span className="text-[11px] text-[#666] tabular-nums">
                    {b.snapshot_at ? `${totals[b.key] ?? 0} из ${groups.reduce((n, g) => n + g.rows.length, 0)}` : 'нет данных'}
                  </span>
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map(group => (
            <Fragment key={group.title}>
              <tr>
                <th colSpan={columns} scope="colgroup"
                  className="text-left text-[11px] font-semibold tracking-widest uppercase text-[#666] pt-5 pb-2 border-b border-[#1F1F1F]">
                  {group.title}
                </th>
              </tr>
              {group.rows.map(row => {
                const open = expanded.has(row.key)
                return (
                  <Fragment key={row.key}>
                    <tr className={`group cursor-pointer ${open ? 'bg-[#141414]' : 'hover:bg-[#121212]'}`}
                      onClick={() => onToggle(row.key)}>
                      <td className="py-2 pr-4 border-b border-[#1A1A1A]">
                        <button
                          type="button"
                          aria-expanded={open}
                          onClick={e => { e.stopPropagation(); onToggle(row.key) }}
                          className="flex items-center gap-2 text-left text-[#E7E7E7] outline-none focus-visible:text-[#86efac]"
                        >
                          <ChevronRight size={14}
                            className={`shrink-0 text-[#666] transition-transform duration-150 ease-out ${open ? 'rotate-90' : ''}`} />
                          {row.title}
                        </button>
                      </td>
                      {banks.map(b => (
                        <td key={b.key} className="py-2 px-2 text-center border-b border-[#1A1A1A]">
                          <Mark cell={row.cells[b.key]} />
                        </td>
                      ))}
                    </tr>
                    {open && (
                      <tr className="bg-[#141414]">
                        <td className="border-b border-[#1A1A1A]" />
                        {banks.map(b => (
                          <td key={b.key} className="align-top px-2 pt-1 pb-4 border-b border-[#1A1A1A]">
                            <CellDetails
                              cell={row.cells[b.key]}
                              isAdmin={isAdmin}
                              saving={saving.has(cellId(row.key, b.key))}
                              onOverride={present => onOverride(row.key, b.key, present)}
                            />
                          </td>
                        ))}
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
