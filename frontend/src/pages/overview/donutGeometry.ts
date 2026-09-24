import { bankColor, bankEdge, bankLabel } from '../../bankMeta'
import type { Summary } from '../../types'

export type ChartMode = 'methods' | 'services'

export interface Segment {
  bank: string
  label: string
  color: string
  /** Hairline for the fill — equal to `color` unless the fill is too pale for
      the current surface. See `bankEdge`. */
  edge: string
  value: number
  pct: number
  startAngle: number
  endAngle: number
  midAngle: number
}

export const CX = 160
export const CY = 160
export const R_OUT = 138
export const R_IN = 88
export const EXPLODE = 10
export const SIZE = 320

/* Half-gap in radians. At the outer radius this leaves roughly 2px of bare
   surface between neighbouring fills, which is what keeps two segments from
   reading as one shape. */
const GAP = 0.01

export function donutPath(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startAngle: number,
  endAngle: number,
  gap = GAP,
): string {
  const sa = startAngle + gap
  const ea = endAngle - gap
  if (ea - sa < 0.001) return ''
  const large = ea - sa > Math.PI ? 1 : 0
  const c = Math.cos
  const s = Math.sin
  const ox1 = cx + outerR * c(sa)
  const oy1 = cy + outerR * s(sa)
  const ox2 = cx + outerR * c(ea)
  const oy2 = cy + outerR * s(ea)
  const ix1 = cx + innerR * c(ea)
  const iy1 = cy + innerR * s(ea)
  const ix2 = cx + innerR * c(sa)
  const iy2 = cy + innerR * s(sa)
  return `M${ox1},${oy1} A${outerR},${outerR} 0 ${large} 1 ${ox2},${oy2} L${ix1},${iy1} A${innerR},${innerR} 0 ${large} 0 ${ix2},${iy2}Z`
}

export function buildSegments(summary: Summary, mode: ChartMode): Segment[] {
  const pick = (bank: Summary['banks'][number]) => (mode === 'methods' ? bank.methods : bank.services)
  const total = summary.banks.reduce((sum, bank) => sum + pick(bank), 0)
  if (!total) return []

  let angle = -Math.PI / 2

  /* Sorted by size for readability. The color still comes from the bank's own
     token, so the ordering never repaints anything. */
  return summary.banks
    .filter((bank) => pick(bank) > 0)
    .sort((a, b) => pick(b) - pick(a))
    .map((bank) => {
      const value = pick(bank)
      const pct = value / total
      const startAngle = angle
      angle += pct * 2 * Math.PI
      return {
        bank: bank.name,
        label: bankLabel(bank.name),
        color: bankColor(bank.name),
        edge: bankEdge(bank.name),
        value,
        pct,
        startAngle,
        endAngle: angle,
        midAngle: (startAngle + angle) / 2,
      }
    })
}

/**
 * Which segment sits under a point, in viewBox coordinates.
 *
 * Hit testing is done on the angle rather than on the paths themselves: an
 * active segment translates outward, and a translated path slides out from
 * under the cursor, which would produce a mouseleave/mouseenter loop. The
 * angular range never moves.
 */
export function segmentAtPoint(segs: readonly Segment[], x: number, y: number): string | null {
  const dx = x - CX
  const dy = y - CY
  const distance = Math.sqrt(dx * dx + dy * dy)

  if (distance < R_IN - 6 || distance > R_OUT + EXPLODE + 12) return null

  let angle = Math.atan2(dy, dx)
  if (angle < -Math.PI / 2) angle += 2 * Math.PI

  return segs.find((seg) => angle >= seg.startAngle && angle < seg.endAngle)?.bank ?? null
}
