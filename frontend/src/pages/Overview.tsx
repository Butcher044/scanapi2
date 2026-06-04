import { useEffect, useState, useCallback, useRef } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Wallet, ArrowUp, ArrowDown, ExternalLink, ChevronsUpDown } from 'lucide-react'
import { api } from '../api'
import type { Summary, Change } from '../types'
import BankBadge from '../components/BankBadge'
import ActionBadge from '../components/ActionBadge'
import TypeBadge from '../components/TypeBadge'

// ── Design tokens ─────────────────────────────────────────────────────────────

const BANK_CFG: Record<string, { color: string; glow: string; label: string; light: string }> = {
  tbank:    { color: '#fbbf24', glow: 'rgba(251,191,36,0.55)',   label: 'Т-Банк',      light: 'rgba(251,191,36,0.12)'  },
  alfabank: { color: '#f87171', glow: 'rgba(248,113,113,0.55)',  label: 'Альфа-Банк',  light: 'rgba(248,113,113,0.12)' },
  sber:     { color: '#86efac', glow: 'rgba(134,239,172,0.55)',  label: 'Сбер',         light: 'rgba(134,239,172,0.12)' },
  tochka:   { color: '#60a5fa', glow: 'rgba(96,165,250,0.55)',   label: 'Точка',        light: 'rgba(96,165,250,0.12)'  },
}

// ── SVG math ──────────────────────────────────────────────────────────────────

function donutPath(
  cx: number, cy: number,
  innerR: number, outerR: number,
  startAngle: number, endAngle: number,
  gap = 0.022,
): string {
  const sa = startAngle + gap
  const ea = endAngle - gap
  if (ea - sa < 0.001) return ''
  const large = ea - sa > Math.PI ? 1 : 0
  const c = Math.cos, s = Math.sin
  const ox1 = cx + outerR * c(sa), oy1 = cy + outerR * s(sa)
  const ox2 = cx + outerR * c(ea), oy2 = cy + outerR * s(ea)
  const ix1 = cx + innerR * c(ea), iy1 = cy + innerR * s(ea)
  const ix2 = cx + innerR * c(sa), iy2 = cy + innerR * s(sa)
  return `M${ox1},${oy1} A${outerR},${outerR} 0 ${large} 1 ${ox2},${oy2} L${ix1},${iy1} A${innerR},${innerR} 0 ${large} 0 ${ix2},${iy2}Z`
}

type ChartMode = 'methods' | 'services'

interface Segment {
  bank: string; value: number; pct: number
  color: string; glow: string; light: string; label: string
  startAngle: number; endAngle: number; midAngle: number
}

function buildSegments(summary: Summary, mode: ChartMode): Segment[] {
  const pick = (b: typeof summary.banks[0]) => mode === 'methods' ? b.methods : b.services
  const total = summary.banks.reduce((s, b) => s + pick(b), 0)
  if (!total) return []
  let angle = -Math.PI / 2
  return summary.banks
    .filter(b => pick(b) > 0)
    .sort((a, b) => pick(b) - pick(a))
    .map(b => {
      const cfg = BANK_CFG[b.name] ?? { color: '#64748b', glow: 'rgba(100,116,139,0.4)', light: 'rgba(100,116,139,0.1)', label: b.name }
      const val  = pick(b)
      const pct  = val / total
      const sa   = angle
      angle     += pct * 2 * Math.PI
      const ea   = angle
      const mid  = (sa + ea) / 2
      return { bank: b.name, value: val, pct, ...cfg, startAngle: sa, endAngle: ea, midAngle: mid }
    })
}

// ── Donut chart ───────────────────────────────────────────────────────────────

const CX = 160, CY = 160, R_OUT = 138, R_IN = 84, EXPLODE = 15, SIZE = 320

function DonutChart({ summary, active, setActive, mode }: {
  summary: Summary
  active: string | null
  setActive: (b: string | null) => void
  mode: ChartMode
}) {
  const [mounted, setMounted] = useState(false)
  const segs = buildSegments(summary, mode)
  const total = segs.reduce((s, seg) => s + seg.value, 0)

  useEffect(() => {
    setMounted(false)
    const t = setTimeout(() => setMounted(true), 80)
    return () => clearTimeout(t)
  }, [total, mode])

  // ── Geometry-based hit detection (no per-path events → no flicker) ─────────
  // When a segment explodes outward, the element leaves the cursor causing
  // mouseleave→mouseenter loops. Instead we compute which segment the cursor
  // is over from the angle relative to the center — the segment's original
  // angular range never changes even when it translates.
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!segs.length) return
    const rect = e.currentTarget.getBoundingClientRect()
    // Map pixel coords → SVG viewBox coords
    const sx = SIZE / rect.width
    const sy = SIZE / rect.height
    const mx = (e.clientX - rect.left) * sx - CX
    const my = (e.clientY - rect.top)  * sy - CY
    const dist = Math.sqrt(mx * mx + my * my)

    // Outside the donut ring (+ generous padding for exploded segment)
    if (dist < R_IN - 6 || dist > R_OUT + EXPLODE + 12) {
      setActive(null)
      return
    }

    // Normalize atan2 output to match segment range that starts at -π/2
    let angle = Math.atan2(my, mx)
    if (angle < -Math.PI / 2) angle += 2 * Math.PI

    for (const seg of segs) {
      if (angle >= seg.startAngle && angle < seg.endAngle) {
        setActive(seg.bank)
        return
      }
    }
    setActive(null)
  }

  if (!segs.length) {
    return (
      <div className="flex items-center justify-center" style={{ width: SIZE, height: SIZE }}>
        <p className="text-[#666] text-sm text-center">
          Нет данных<br />
          <span className="text-xs">Нажмите кнопку ПАРСИНГ</span>
        </p>
      </div>
    )
  }

  const activeSeg = segs.find(s => s.bank === active)

  return (
    <div
      style={{
        opacity: mounted ? 1 : 0,
        transform: mounted ? 'scale(1)' : 'scale(0.88)',
        transition: 'opacity 0.55s ease, transform 0.55s cubic-bezier(0.34,1.4,0.64,1)',
      }}
    >
      <svg
        width={SIZE} height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="overflow-visible"
        style={{
          filter: 'drop-shadow(0 0 30px rgba(0,0,0,0.7))',
          cursor: active ? 'pointer' : 'default',
        }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setActive(null)}
      >
        <defs>
          {segs.map(s => (
            <filter key={`gf-${s.bank}`} id={`gf-${s.bank}`} x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
              <feColorMatrix in="blur" type="saturate" values="2" result="sat" />
              <feMerge>
                <feMergeNode in="sat" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          ))}
          <radialGradient id="hole-grad" cx="50%" cy="40%" r="60%">
            <stop offset="0%" stopColor="#1f1f1f" />
            <stop offset="100%" stopColor="#0a0a0a" />
          </radialGradient>
        </defs>

        {/* Subtle outer ring */}
        <circle cx={CX} cy={CY} r={R_OUT + 6} fill="none" stroke="#ffffff" strokeWidth="1" opacity="0.04" />

        {/* Segments — no mouse handlers here, SVG handles it */}
        {segs.map(s => {
          const isActive = active === s.bank
          const isOther  = active !== null && !isActive
          const dx = isActive ? Math.cos(s.midAngle) * EXPLODE : 0
          const dy = isActive ? Math.sin(s.midAngle) * EXPLODE : 0

          return (
            <path
              key={s.bank}
              d={donutPath(CX, CY, R_IN, R_OUT, s.startAngle, s.endAngle)}
              fill={s.color}
              opacity={isOther ? 0.25 : 1}
              filter={isActive ? `url(#gf-${s.bank})` : undefined}
              style={{
                transform: `translate(${dx}px,${dy}px)`,
                transition: 'transform 0.38s cubic-bezier(0.34,1.56,0.64,1), opacity 0.22s ease',
                pointerEvents: 'none', // SVG handles all pointer events
              }}
            />
          )
        })}

        {/* Inner hole */}
        <circle cx={CX} cy={CY} r={R_IN - 1} fill="url(#hole-grad)" />

        {/* Center text */}
        <g style={{ transition: 'opacity 0.25s ease' }}>
          {activeSeg ? (
            <>
              <text
                x={CX} y={CY - 20}
                textAnchor="middle"
                fill={activeSeg.color}
                fontSize={30} fontWeight="700"
                fontFamily="Space Grotesk, sans-serif"
                style={{ transition: 'fill 0.2s ease' }}
              >
                {activeSeg.value.toLocaleString('ru')}
              </text>
              <text x={CX} y={CY + 5} textAnchor="middle" fill="#666" fontSize={11} fontFamily="Space Grotesk, sans-serif">
                {mode === 'methods' ? 'методов' : 'сервисов'}
              </text>
              <text x={CX} y={CY + 24} textAnchor="middle" fill={activeSeg.color} fontSize={11} fontWeight="500" fontFamily="Space Grotesk, sans-serif" opacity="0.8">
                {activeSeg.label}
              </text>
              <text x={CX} y={CY + 42} textAnchor="middle" fill="#555" fontSize={10} fontFamily="Space Grotesk, sans-serif">
                {(activeSeg.pct * 100).toFixed(1)}%
              </text>
            </>
          ) : (
            <>
              <text
                x={CX} y={CY - 16}
                textAnchor="middle"
                fill="#E7E7E7"
                fontSize={34} fontWeight="700"
                fontFamily="Space Grotesk, sans-serif"
              >
                {total.toLocaleString('ru')}
              </text>
              <text x={CX} y={CY + 10} textAnchor="middle" fill="#919191" fontSize={12} fontFamily="Space Grotesk, sans-serif">
                {mode === 'methods' ? 'эндпоинтов' : 'сервисов'}
              </text>
              <text x={CX} y={CY + 28} textAnchor="middle" fill="#555" fontSize={10} fontFamily="Space Grotesk, sans-serif">
                {summary.banks.filter(b => b.methods > 0).length} банков
              </text>
            </>
          )}
        </g>
      </svg>
    </div>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend({ segs, summary, active, setActive, mounted, mode, setMode }: {
  segs: Segment[]; summary: Summary
  active: string | null; setActive: (b: string | null) => void
  mounted: boolean
  mode: ChartMode; setMode: (m: ChartMode) => void
}) {
  return (
    <div className="flex flex-col justify-center gap-3 min-w-0">
      {/* Title + toggle */}
      <div className="mb-2 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-white">Распределение API</h3>
          <p className="text-xs text-[#666] mt-0.5">
            {mode === 'methods' ? 'По количеству эндпоинтов' : 'По количеству сервисов'}
          </p>
        </div>
        <div className="flex items-center gap-1 bg-[#141414] border border-[#2a2a2a] rounded-lg p-0.5 shrink-0">
          {(['methods', 'services'] as ChartMode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                mode === m
                  ? 'bg-[#2a2a2a] text-[#E7E7E7] shadow-sm'
                  : 'text-[#555] hover:text-[#919191]'
              }`}
            >
              {m === 'methods' ? 'Методы' : 'Сервисы'}
            </button>
          ))}
        </div>
      </div>

      {segs.map((s, i) => {
        const isActive  = active === s.bank
        const isOther   = active !== null && !isActive
        const barWidth  = mounted ? `${s.pct * 100}%` : '0%'

        return (
          <div
            key={s.bank}
            className="group cursor-pointer"
            style={{
              opacity: isOther ? 0.4 : 1,
              transition: 'opacity 0.2s ease',
              transitionDelay: mounted ? `${i * 60}ms` : '0ms',
            }}
            onMouseEnter={() => setActive(s.bank)}
            onMouseLeave={() => setActive(null)}
          >
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{
                    backgroundColor: s.color,
                    boxShadow: isActive ? `0 0 8px ${s.color}` : 'none',
                    transition: 'box-shadow 0.2s ease',
                  }}
                />
                <span className={`text-sm font-medium transition-colors ${isActive ? 'text-white' : 'text-[#919191] group-hover:text-[#E7E7E7]'}`}>
                  {s.label}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[#666]">{(s.pct * 100).toFixed(1)}%</span>
                <span className={`text-sm font-semibold tabular-nums transition-colors ${isActive ? 'text-white' : 'text-[#919191]'}`}>
                  {s.value.toLocaleString('ru')}
                </span>
              </div>
            </div>
            {/* Progress bar */}
            <div className="h-[3px] rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(255,255,255,0.06)' }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: barWidth,
                  backgroundColor: s.color,
                  boxShadow: isActive ? `0 0 6px ${s.color}` : 'none',
                  transition: `width 0.8s cubic-bezier(0.4,0,0.2,1) ${i * 80}ms, box-shadow 0.2s ease`,
                }}
              />
            </div>
          </div>
        )
      })}

      {/* Totals */}
      <div className="mt-3 pt-4 border-t border-[#1F1F1F] grid grid-cols-2 gap-3">
        <div>
          <p className="text-[10px] text-[#555] uppercase tracking-wider mb-1">Сервисов</p>
          <p className="text-xl font-bold text-white">{summary.total_services}</p>
        </div>
        <div>
          <p className="text-[10px] text-[#555] uppercase tracking-wider mb-1">Методов</p>
          <p className="text-xl font-bold text-white">{summary.total_methods.toLocaleString('ru')}</p>
        </div>
        <div>
          <p className="text-[10px] text-[#555] uppercase tracking-wider mb-1">Изм. сегодня</p>
          <p className={`text-xl font-bold ${summary.changes_today > 0 ? 'text-[#86efac]' : 'text-white'}`}>
            {summary.changes_today > 0 ? `+${summary.changes_today}` : summary.changes_today}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-[#555] uppercase tracking-wider mb-1">За неделю</p>
          <p className={`text-xl font-bold ${summary.changes_week > 0 ? 'text-[#86efac]' : 'text-white'}`}>
            {summary.changes_week > 0 ? `+${summary.changes_week}` : summary.changes_week}
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Overview() {
  const { refresh } = useOutletContext<{ refresh: number }>()
  const [summary, setSummary]   = useState<Summary | null>(null)
  const [recent, setRecent]     = useState<Change[]>([])
  const [active, setActive]     = useState<string | null>(null)
  const [chartMounted, setChartMounted] = useState(false)
  const [mode, setMode]         = useState<ChartMode>('methods')

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([api.summary(), api.changes({ limit: 10 })])
    setSummary(s)
    setRecent(c.changes)
  }, [])

  useEffect(() => { load() }, [load, refresh])
  useEffect(() => { const id = setInterval(load, 60_000); return () => clearInterval(id) }, [load])

  // Trigger legend mount animation when summary loads or mode changes
  useEffect(() => {
    if (summary?.total_methods) {
      setChartMounted(false)
      const t = setTimeout(() => setChartMounted(true), 150)
      return () => clearTimeout(t)
    }
  }, [summary?.total_methods, mode])

  const segs = summary ? buildSegments(summary, mode) : []

  return (
    <div className="flex flex-col gap-6">

      {/* ── Metrics card ── */}
      <div className="flex flex-col xl:flex-row gap-8 xl:items-center justify-between p-6 bg-[#0D0D0D] rounded-2xl">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-[#919191]">
            <Wallet className="h-5 w-5" />
            <span className="text-lg">Всего эндпоинтов</span>
          </div>
          <div className="text-5xl md:text-4xl lg:text-5xl font-bold text-white">
            {(summary?.total_methods ?? 0).toLocaleString('ru')}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 xl:gap-16">
          {[
            { label: 'Банков', value: summary?.banks.length ?? 0, color: false },
            { label: 'Сервисов', value: summary?.total_services ?? 0, color: false },
            { label: 'Изм. сегодня', value: summary?.changes_today ?? 0, color: true },
            { label: 'Изм. за неделю', value: summary?.changes_week ?? 0, color: true },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex flex-col gap-1">
              <span className="text-[#919191] text-sm">{label}</span>
              <span className={`text-2xl md:text-xl lg:text-2xl font-semibold ${color && value > 0 ? 'text-[#86efac]' : 'text-white'}`}>
                {color && value > 0 ? `+${value}` : value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Donut chart + Legend ── */}
      <div className="bg-[#0D0D0D] rounded-2xl p-6 md:p-8">
        <div className="flex flex-col md:flex-row items-center gap-8 md:gap-12">
          {/* Chart */}
          <div className="shrink-0">
            {summary && (
              <DonutChart summary={summary} active={active} setActive={setActive} mode={mode} />
            )}
          </div>

          {/* Legend */}
          <div className="flex-1 min-w-0 w-full">
            {summary && segs.length > 0 ? (
              <Legend
                segs={segs} summary={summary}
                active={active} setActive={setActive}
                mounted={chartMounted}
                mode={mode} setMode={setMode}
              />
            ) : (
              <div className="flex flex-col gap-4">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="animate-pulse">
                    <div className="h-4 bg-[#1A1A1A] rounded w-32 mb-2" />
                    <div className="h-[3px] bg-[#1A1A1A] rounded" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Recent changes ── */}
      <div className="bg-[#0D0D0D] rounded-2xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-medium text-white">Последние изменения</h2>
          <a href="/changes" className="text-sm text-[#919191] hover:text-[#E7E7E7] transition-colors">Все →</a>
        </div>

        <table className="w-full">
          <thead>
            <tr className="text-[#919191] text-sm">
              <th className="pb-4 text-left font-medium pl-2">
                <div className="flex items-center gap-1">Банк <ChevronsUpDown className="h-3 w-3" /></div>
              </th>
              <th className="pb-4 text-left font-medium">Тип</th>
              <th className="pb-4 text-left font-medium">Изменение</th>
              <th className="pb-4 text-left font-medium">Сущность</th>
              <th className="pb-4 text-right font-medium">Дата</th>
              <th className="pb-4 text-right font-medium pr-2" />
            </tr>
          </thead>
          <tbody>
            {recent.map((c, i) => {
              const isFirst = i === 0
              return (
                <tr
                  key={c.id}
                  className={`transition-colors border-b border-transparent last:border-0 ${isFirst ? 'bg-[#1A1A1A]' : 'hover:bg-[#1A1A1A]'}`}
                >
                  <td className="py-3 pl-2 rounded-l-xl"><BankBadge bank={c.bank} label={c.bank_label} /></td>
                  <td className="py-3"><TypeBadge type={c.type} /></td>
                  <td className="py-3"><ActionBadge action={c.action} /></td>
                  <td className="py-3 max-w-[200px]">
                    <span className="font-mono text-xs text-white truncate block" title={c.entity}>{c.entity}</span>
                  </td>
                  <td className="py-3 text-right text-[#919191] text-xs whitespace-nowrap">{c.detected_at}</td>
                  <td className="py-3 text-right pr-2 rounded-r-xl">
                    <div className="flex items-center justify-end gap-1">
                      {c.action === 'added'   && <ArrowUp className="h-4 w-4 text-[#86efac]" />}
                      {c.action === 'removed' && <ArrowDown className="h-4 w-4 text-[#f87171]" />}
                      {c.url && (
                        <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-[#666] hover:text-[#E7E7E7] ml-1">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
            {recent.length === 0 && (
              <tr>
                <td colSpan={6} className="py-10 text-center text-[#666] text-sm">
                  Нет данных — нажмите <span className="text-[#86efac] font-semibold">ПАРСИНГ</span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
