import { useCallback, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Loader2, RefreshCw } from 'lucide-react'
import { useBenchmark } from '../hooks/useBenchmark'
import BenchmarkTable, { type BenchmarkGroup } from '../components/benchmark/BenchmarkTable'
import UnmatchedCard from '../components/benchmark/UnmatchedCard'
import { Card, ghostButton } from '../components/settings/Card'
import type { Benchmark as BenchmarkData, BenchmarkRow, Role } from '../types'

const toggled = (set: ReadonlySet<string>, key: string) =>
  set.has(key) ? new Set([...set].filter(k => k !== key)) : new Set([...set, key])

/** A row differs when the banks with data do not all agree. */
function differs(row: BenchmarkRow, banks: string[]): boolean {
  return new Set(banks.map(b => row.cells[b]?.present)).size > 1
}

function visibleGroups(data: BenchmarkData, onlyDiff: boolean): BenchmarkGroup[] {
  if (!onlyDiff) return data.groups
  const withData = data.banks.filter(b => b.snapshot_at).map(b => b.key)
  return data.groups
    .map(g => ({ ...g, rows: g.rows.filter(r => differs(r, withData)) }))
    .filter(g => g.rows.length > 0)
}

function presentTotals(data: BenchmarkData): Record<string, number> {
  const rows = data.groups.flatMap(g => g.rows)
  return Object.fromEntries(data.banks.map(b => [b.key, rows.filter(r => r.cells[b.key]?.present).length]))
}

export default function Benchmark() {
  const { refresh, role } = useOutletContext<{ refresh: number; role: Role }>()
  const isAdmin = role === 'admin'
  const { data, error, saving, reload, override } = useBenchmark(refresh)
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set())
  const [onlyDiff, setOnlyDiff] = useState(false)

  const toggle = useCallback((key: string) => setExpanded(set => toggled(set, key)), [])
  const onOverride = useCallback(
    (capability: string, bank: string, present: boolean | null) => void override(capability, bank, present),
    [override],
  )
  const groups = useMemo(() => (data ? visibleGroups(data, onlyDiff) : []), [data, onlyDiff])
  const totals = useMemo(() => (data ? presentTotals(data) : {}), [data])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-bold tracking-wide">Бенчмарк</h1>
          <p className="text-sm text-[#919191]">
            Какие возможности есть в API каждого банка. Нажмите на строку, чтобы увидеть, какие сервисы дали «+».
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-[#919191] cursor-pointer select-none">
          <input type="checkbox" checked={onlyDiff} onChange={e => setOnlyDiff(e.target.checked)}
            className="accent-[#86efac] w-3.5 h-3.5" />
          Только различия
        </label>
      </div>

      {error && (
        <div className="flex items-center gap-3 flex-wrap">
          <p role="alert" className="text-sm text-[#f87171]">{error}</p>
          {!data && (
            <button type="button" className={ghostButton} onClick={reload}>
              <RefreshCw size={12} /> Повторить
            </button>
          )}
        </div>
      )}

      {data ? (
        <>
          <Card title="МАТРИЦА ВОЗМОЖНОСТЕЙ">
            {groups.length > 0 ? (
              <BenchmarkTable
                banks={data.banks}
                groups={groups}
                totals={totals}
                expanded={expanded}
                isAdmin={isAdmin}
                saving={saving}
                onToggle={toggle}
                onOverride={onOverride}
              />
            ) : (
              <p className="text-sm text-[#919191]">Различий нет — у всех банков одинаковый набор.</p>
            )}
            {isAdmin && (
              <p className="text-xs text-[#666]">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#fbbf24] mr-1.5 align-middle" />
                значение выставлено вручную. Править ячейку — в раскрытой строке.
              </p>
            )}
          </Card>
          <UnmatchedCard banks={data.banks} unmatched={data.unmatched} />
        </>
      ) : !error && (
        <div className="flex justify-center py-12"><Loader2 className="animate-spin text-[#86efac]" /></div>
      )}
    </div>
  )
}
