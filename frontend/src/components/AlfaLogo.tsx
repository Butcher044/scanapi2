type Props = {
  size?: number
  className?: string
}

/**
 * Alfa mark, inlined so it costs no request and scales with the layout.
 * The red is the literal brand value and is deliberately not tokenised — the
 * logo must stay the same color in both themes.
 */
export function AlfaLogo({ size = 28, className }: Props) {
  return (
    <svg
      viewBox="0 0 28 28"
      width={size}
      height={size}
      fill="none"
      className={className}
      role="img"
      aria-label="Альфа-Банк"
    >
      <path fill="#EF3124" d="M0 0h28v28H0z" />
      <path
        fill="#fff"
        d="M8.743 19.815h10.514V22H8.743zM15.912 7.6c-.301-.894-.646-1.6-1.83-1.6s-1.552.703-1.867 1.6l-3.253 9.247h2.157l.75-2.198h4.154l.698 2.198h2.295zm-3.414 5.192 1.475-4.388h.054l1.393 4.388z"
      />
    </svg>
  )
}
