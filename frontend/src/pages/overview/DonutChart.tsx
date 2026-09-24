import { useEffect, useState, type PointerEvent } from 'react'
import { HAIRLINE_WIDTH } from '../../bankMeta'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion'
import {
  CX,
  CY,
  EXPLODE,
  R_IN,
  R_OUT,
  SIZE,
  donutPath,
  segmentAtPoint,
  type ChartMode,
  type Segment,
} from './donutGeometry'

type Props = {
  segments: readonly Segment[]
  bankCount: number
  mode: ChartMode
  active: string | null
  onActiveChange: (bank: string | null) => void
}

type Unit = { active: string; total: string }

const MODE_UNIT: Record<ChartMode, Unit> = {
  methods: { active: 'методов', total: 'эндпоинтов' },
  services: { active: 'сервисов', total: 'сервисов' },
}

function EmptyState() {
  return (
    <div className="grid aspect-square w-full max-w-[320px] place-items-center rounded-full border border-dashed border-line">
      <p className="px-6 text-center text-sm text-ink-faint">
        Нет данных
        <br />
        <span className="text-xs">Запустите парсинг</span>
      </p>
    </div>
  )
}

/** Shared placement and timing, so a fill and its hairline never drift apart. */
function segmentStyle(seg: Segment, isActive: boolean, reducedMotion: boolean) {
  const dx = isActive ? Math.cos(seg.midAngle) * EXPLODE : 0
  const dy = isActive ? Math.sin(seg.midAngle) * EXPLODE : 0

  return {
    transform: `translate(${dx}px,${dy}px)`,
    transition: reducedMotion
      ? 'opacity 1ms'
      : 'transform 240ms var(--ease-out), opacity 180ms var(--ease-out)',
    pointerEvents: 'none' as const,
  }
}

/**
 * Fills first, then every hairline on top of all of them. The two passes are
 * what let a lifted segment keep its surface ring and its brand edge at once:
 * drawn in one pass the ring would land above the edge and swallow it.
 */
function Segments({
  segments,
  active,
  reducedMotion,
}: {
  segments: readonly Segment[]
  active: string | null
  reducedMotion: boolean
}) {
  /* Traced once and reused by both passes, so the trig never runs twice for
     the same arc on a pointer move. */
  const drawn = segments.map((seg) => ({
    seg,
    d: donutPath(CX, CY, R_IN, R_OUT, seg.startAngle, seg.endAngle),
  }))
  const opacityOf = (seg: Segment) => (active !== null && active !== seg.bank ? 0.3 : 1)

  return (
    <>
      {drawn.map(({ seg, d }) => (
        <path
          key={seg.bank}
          d={d}
          fill={seg.color}
          opacity={opacityOf(seg)}
          /* A 2px surface ring separates the lifted segment from the ones it
             now overlaps, instead of a blur filter that repaints the whole
             subtree on every frame. */
          stroke="rgb(var(--c-surface))"
          strokeWidth={active === seg.bank ? HAIRLINE_WIDTH * 2 : 0}
          style={segmentStyle(seg, active === seg.bank, reducedMotion)}
        />
      ))}
      {drawn.map(({ seg, d }) => (
        <path
          key={`${seg.bank}-edge`}
          d={d}
          fill="none"
          opacity={opacityOf(seg)}
          /* Invisible for every bank whose fill already clears 3:1 against the
             card, because there the edge token equals the fill. */
          stroke={seg.edge}
          strokeWidth={HAIRLINE_WIDTH}
          style={segmentStyle(seg, active === seg.bank, reducedMotion)}
        />
      ))}
    </>
  )
}

/**
 * The hole's readout. Values wear ink tokens and the small dot above them
 * carries identity, so the reading never depends on a colored numeral.
 */
function CenterLabel({
  activeSeg,
  unit,
  total,
  bankCount,
}: {
  activeSeg: Segment | null
  unit: Unit
  total: number
  bankCount: number
}) {
  const headline = activeSeg ? activeSeg.value : total
  const caption = activeSeg ? activeSeg.label : unit.total
  const footnote = activeSeg
    ? `${(activeSeg.pct * 100).toFixed(1)}% · ${unit.active}`
    : `${bankCount} банков`

  return (
    <g aria-hidden>
      {activeSeg && (
        <circle
          cx={CX}
          cy={CY - 42}
          r={4.5}
          fill={activeSeg.color}
          stroke={activeSeg.edge}
          strokeWidth={HAIRLINE_WIDTH}
        />
      )}
      <text
        x={CX}
        y={activeSeg ? CY - 8 : CY - 6}
        textAnchor="middle"
        fill="rgb(var(--c-ink))"
        fontSize={activeSeg ? 30 : 34}
        fontWeight="700"
      >
        {headline.toLocaleString('ru')}
      </text>
      <text
        x={CX}
        y={activeSeg ? CY + 14 : CY + 18}
        textAnchor="middle"
        fill="rgb(var(--c-ink-muted))"
        fontSize={12}
      >
        {caption}
      </text>
      <text
        x={CX}
        y={activeSeg ? CY + 34 : CY + 38}
        textAnchor="middle"
        fill="rgb(var(--c-ink-faint))"
        fontSize={11}
      >
        {footnote}
      </text>
    </g>
  )
}

/**
 * Pointer-driven donut. Keyboard access lives in `DistributionLegend`, whose
 * rows raise the same active-bank state on focus.
 */
export function DonutChart({ segments, bankCount, mode, active, onActiveChange }: Props) {
  const [shown, setShown] = useState(false)
  const reducedMotion = usePrefersReducedMotion()
  const total = segments.reduce((sum, seg) => sum + seg.value, 0)

  useEffect(() => {
    setShown(false)
    const timer = setTimeout(() => setShown(true), 60)
    return () => clearTimeout(timer)
  }, [total, mode])

  if (!segments.length) return <EmptyState />

  const activeSeg = segments.find((seg) => seg.bank === active) ?? null
  const unit = MODE_UNIT[mode]

  const pick = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const x = ((event.clientX - rect.left) * SIZE) / rect.width
    const y = ((event.clientY - rect.top) * SIZE) / rect.height
    onActiveChange(segmentAtPoint(segments, x, y))
  }

  const label = activeSeg
    ? `${activeSeg.label}: ${activeSeg.value} ${unit.active}, ${(activeSeg.pct * 100).toFixed(1)}%`
    : `Всего ${total} ${unit.total} по ${bankCount} банкам`

  return (
    <div
      className="w-full max-w-[320px]"
      style={
        reducedMotion
          ? undefined
          : {
              opacity: shown ? 1 : 0,
              transform: shown ? 'scale(1)' : 'scale(0.96)',
              transition: 'opacity 260ms var(--ease-out), transform 260ms var(--ease-out)',
            }
      }
    >
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="img"
        aria-label={label}
        className="h-auto w-full touch-manipulation"
        style={{ cursor: active ? 'pointer' : 'default' }}
        onPointerMove={pick}
        onPointerDown={pick}
        onPointerLeave={() => onActiveChange(null)}
      >
        <Segments segments={segments} active={active} reducedMotion={reducedMotion} />
        <circle cx={CX} cy={CY} r={R_IN - 1} fill="rgb(var(--c-surface))" />
        <CenterLabel activeSeg={activeSeg} unit={unit} total={total} bankCount={bankCount} />
      </svg>
    </div>
  )
}
