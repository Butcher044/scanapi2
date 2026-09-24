import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { api } from '../api'
import { DistributionLegend } from './overview/DistributionLegend'
import { DonutChart } from './overview/DonutChart'
import { RecentChangesTable } from './overview/RecentChangesTable'
import { StatTiles } from './overview/StatTiles'
import { buildSegments, type ChartMode } from './overview/donutGeometry'
import type { Change, Summary } from '../types'

const POLL_MS = 60_000

function LegendSkeleton() {
  return (
    <div className="flex w-full flex-col gap-4" aria-hidden>
      {[0, 1, 2, 3].map((row) => (
        <div key={row} className="animate-pulse">
          <div className="mb-2 h-4 w-32 rounded bg-raised" />
          <div className="h-[3px] rounded bg-raised" />
        </div>
      ))}
    </div>
  )
}

export default function Overview() {
  const { refresh } = useOutletContext<{ refresh: number }>()
  const [summary, setSummary] = useState<Summary | null>(null)
  const [recent, setRecent] = useState<Change[]>([])
  const [active, setActive] = useState<string | null>(null)
  const [mode, setMode] = useState<ChartMode>('methods')
  const [revealed, setRevealed] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const latestLoad = useRef(0)

  const load = useCallback(async () => {
    const id = ++latestLoad.current
    try {
      const [nextSummary, nextChanges] = await Promise.all([
        api.summary(),
        api.changes({ limit: 10 }),
      ])
      if (id !== latestLoad.current) return
      setSummary(nextSummary)
      setRecent(nextChanges.changes)
      setLoadError(false)
    } catch {
      if (id === latestLoad.current) setLoadError(true)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refresh])

  useEffect(() => {
    const id = setInterval(() => void load(), POLL_MS)
    /* Bumping the counter on unmount drops any response still in flight. */
    return () => {
      clearInterval(id)
      latestLoad.current += 1
    }
  }, [load])

  /* Bars grow from zero once the data is in place, not on every poll. */
  useEffect(() => {
    if (!summary?.total_methods) return
    setRevealed(false)
    const timer = setTimeout(() => setRevealed(true), 120)
    return () => clearTimeout(timer)
  }, [summary?.total_methods, mode])

  const segments = useMemo(() => (summary ? buildSegments(summary, mode) : []), [summary, mode])
  const bankCount = useMemo(
    () => summary?.banks.filter((bank) => bank.methods > 0).length ?? 0,
    [summary],
  )

  return (
    <div className="flex flex-col gap-5 sm:gap-6">
      {loadError && (
        <div
          role="alert"
          className="rounded-2xl border border-danger/40 bg-danger-tint px-5 py-3 text-sm text-danger"
        >
          Не удалось загрузить сводку — данные могут быть устаревшими
        </div>
      )}

      <StatTiles summary={summary} />

      <section className="rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6 md:p-8">
        {/* Stacked until `lg`: at tablet width the sidebar is already back, and a
            side-by-side donut would squeeze the legend to about 180px — too narrow
            for the name, share and value to sit on one line. */}
        <div className="flex flex-col items-center gap-8 lg:flex-row lg:gap-12 xl:gap-14">
          <div className="flex w-full shrink-0 justify-center lg:w-auto">
            <DonutChart
              segments={segments}
              bankCount={bankCount}
              mode={mode}
              active={active}
              onActiveChange={setActive}
            />
          </div>

          <div className="w-full min-w-0 flex-1">
            {segments.length > 0 ? (
              <DistributionLegend
                segments={segments}
                mode={mode}
                onModeChange={setMode}
                active={active}
                onActiveChange={setActive}
                revealed={revealed}
              />
            ) : (
              <LegendSkeleton />
            )}
          </div>
        </div>
      </section>

      <RecentChangesTable changes={recent} />
    </div>
  )
}
