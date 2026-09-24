import { bankDotStyle, bankRingShadow } from '../../bankMeta'
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion'
import type { ChartMode, Segment } from './donutGeometry'

type Props = {
  segments: readonly Segment[]
  mode: ChartMode
  onModeChange: (mode: ChartMode) => void
  active: string | null
  onActiveChange: (bank: string | null) => void
  revealed: boolean
}

const MODES: readonly { id: ChartMode; label: string }[] = [
  { id: 'methods', label: 'Методы' },
  { id: 'services', label: 'Сервисы' },
]

function ModeSwitch({ mode, onModeChange }: Pick<Props, 'mode' | 'onModeChange'>) {
  return (
    <div
      role="group"
      aria-label="Единица измерения"
      className="flex shrink-0 items-center gap-0.5 rounded-lg border border-line bg-raised p-0.5"
    >
      {MODES.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={() => onModeChange(item.id)}
          aria-pressed={mode === item.id}
          className={[
            'press rounded-[7px] px-3 py-1 text-xs font-medium transition-colors duration-150',
            mode === item.id
              ? 'bg-surface text-ink shadow-card'
              : 'text-ink-faint hover:text-ink-muted',
          ].join(' ')}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

/**
 * The legend doubles as the chart's table view: every segment's exact value and
 * share is readable without hovering anything, which is what keeps the donut
 * usable on a phone and for anyone who cannot separate two of the hues.
 *
 * It is also the chart's keyboard surrogate. The donut itself is pointer-only;
 * these rows are what put the same highlight under Tab, so a refactor that drops
 * their focus handlers takes the chart's keyboard access with it.
 */
export function DistributionLegend({
  segments,
  mode,
  onModeChange,
  active,
  onActiveChange,
  revealed,
}: Props) {
  const reducedMotion = usePrefersReducedMotion()

  return (
    <div className="flex min-w-0 flex-col justify-center gap-3">
      <div className="mb-1 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-ink sm:text-lg">Распределение API</h3>
          <p className="mt-0.5 text-xs text-ink-faint">
            {mode === 'methods' ? 'По количеству эндпоинтов' : 'По количеству сервисов'}
          </p>
        </div>
        <ModeSwitch mode={mode} onModeChange={onModeChange} />
      </div>

      <ul className="flex flex-col gap-3">
        {segments.map((seg, index) => {
          const isActive = active === seg.bank
          const dimmed = active !== null && !isActive

          return (
            <li key={seg.bank}>
              <button
                type="button"
                onMouseEnter={() => onActiveChange(seg.bank)}
                onMouseLeave={() => onActiveChange(null)}
                onFocus={() => onActiveChange(seg.bank)}
                onBlur={() => onActiveChange(null)}
                /* Touch has no hover, so a tap has to be able to drive the
                   highlight too. Deliberately no `aria-pressed`: focus alone
                   flips this state, so it is a preview, not a toggle, and
                   claiming the toggle contract would misreport it. */
                onClick={() => onActiveChange(isActive ? null : seg.bank)}
                className="group block w-full rounded-lg px-1 py-0.5 text-left"
                style={{
                  opacity: dimmed ? 0.45 : 1,
                  transition: reducedMotion ? undefined : 'opacity 180ms var(--ease-out)',
                }}
              >
                <span className="mb-1.5 flex items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={bankDotStyle(seg.bank)}
                    />
                    <span
                      className={[
                        'truncate text-sm font-medium transition-colors duration-150',
                        isActive ? 'text-ink' : 'text-ink-muted group-hover:text-ink',
                      ].join(' ')}
                    >
                      {seg.label}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-xs tabular-nums text-ink-faint">
                      {(seg.pct * 100).toFixed(1)}%
                    </span>
                    <span
                      className={[
                        'text-sm font-semibold tabular-nums transition-colors duration-150',
                        isActive ? 'text-ink' : 'text-ink-muted',
                      ].join(' ')}
                    >
                      {seg.value.toLocaleString('ru')}
                    </span>
                  </span>
                </span>

                <span className="block h-[3px] overflow-hidden rounded-full bg-line">
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: revealed || reducedMotion ? `${seg.pct * 100}%` : '0%',
                      backgroundColor: seg.color,
                      /* The track is a hairline gray; without this the palest
                         fill would read as an empty bar. Same ring as the dot,
                         minus the background the width animation owns. */
                      boxShadow: bankRingShadow(seg.bank),
                      transition: reducedMotion
                        ? undefined
                        : `width 520ms var(--ease-out) ${index * 60}ms`,
                    }}
                  />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
