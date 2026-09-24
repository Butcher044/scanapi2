/*
 * Bank identity colors.
 *
 * Each bank wears its own brand color, because that is what a reader already
 * associates with it: Альфа #EF3124, Т-Банк #FFDD2D, Сбер #21A038.
 *
 * That choice has a measured cost and the cost is paid deliberately, not
 * ignored. Yellow sits between red and green on the protan/deutan confusion
 * axis, so Т-Банк against Альфа measures ΔE 4.6 under deuteranopia — below the
 * floor of 6 — and Сбер against Альфа measures 3.8. Hue alone therefore cannot
 * carry identity here. Two things make up for it, and a refactor that removes
 * either one breaks the chart for a colorblind reader:
 *
 *   1. Identity is always spelled out. Every mark sits next to its bank's name
 *      — the legend, the badges, the donut's center readout — so the color is
 *      a reminder, never the only cue.
 *   2. Every fill is drawn with a hairline in `bankEdge()`. Yellow measures
 *      1.34:1 against the white card and would otherwise dissolve into it.
 *
 * The `-edge` tokens are computed, not chosen by eye: a bank's edge equals its
 * fill wherever the fill already clears 3:1 against the surface, and is stepped
 * away from the surface where it does not. Only Т-Банк needs one on the light
 * surface and only Точка on the dark one, so on every other mark the hairline
 * is there but invisible.
 *
 * Точка's hex is a PLACEHOLDER. The 2022 rebrand made the brand purple, but the
 * exact value is not published and this environment cannot reach their site
 * (anti-bot challenge). `#6C3FD1` is the violet that separates best from the
 * other three; swap it for the official one when it is known.
 *
 * Values are CSS variable references rather than hex so a bank keeps one color
 * across both themes and nothing here has to know which theme is active.
 */

export type BankId = 'tbank' | 'alfabank' | 'sber' | 'tochka'

/* Fixed assignment order. Color follows the bank, never its rank, so a filter
   that drops a bank must never repaint the survivors. */
export const BANK_ORDER: readonly BankId[] = ['alfabank', 'tbank', 'sber', 'tochka']

export const BANK_COLORS: Record<string, string> = {
  alfabank: 'rgb(var(--c-bank-alfabank))',
  tbank: 'rgb(var(--c-bank-tbank))',
  sber: 'rgb(var(--c-bank-sber))',
  tochka: 'rgb(var(--c-bank-tochka))',
}

export const BANK_LABELS: Record<string, string> = {
  tbank: 'Т-Банк',
  alfabank: 'Альфа-Банк',
  sber: 'Сбер',
  tochka: 'Точка',
}

function bankVar(bank: string): string {
  return BANK_COLORS[bank] ? `--c-bank-${bank}` : '--c-ink-faint'
}

/** Same identity color at a given opacity — for tints, glows and hover washes. */
export function bankColor(bank: string, alpha = 1): string {
  const varName = bankVar(bank)
  return alpha === 1 ? `rgb(var(${varName}))` : `rgb(var(${varName}) / ${alpha})`
}

/**
 * The hairline drawn around a bank's fill. Equal to the fill for every bank
 * whose fill already clears 3:1 against the current surface, so applying it
 * unconditionally costs nothing and never needs a per-bank branch at the call
 * site.
 */
export function bankEdge(bank: string): string {
  const varName = bankVar(bank)
  return BANK_COLORS[bank] ? `rgb(var(${varName}-edge))` : `rgb(var(${varName}))`
}

/** One hairline width for every mark, CSS ring and SVG stroke alike. */
export const HAIRLINE_WIDTH = 1

/**
 * The hairline as an inset ring, which draws it without growing the element's
 * own box. Separate from `bankDotStyle` because filled bars want the ring
 * without inheriting a background they set themselves.
 */
export function bankRingShadow(bank: string): string {
  return `inset 0 0 0 ${HAIRLINE_WIDTH}px ${bankEdge(bank)}`
}

/** The shared look of a bank dot or swatch: the brand fill plus its hairline. */
export function bankDotStyle(bank: string): { backgroundColor: string; boxShadow: string } {
  return {
    backgroundColor: bankColor(bank),
    boxShadow: bankRingShadow(bank),
  }
}

export function bankLabel(bank: string): string {
  return BANK_LABELS[bank] ?? bank
}
