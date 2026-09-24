import { Moon, Sun } from 'lucide-react'
import type { Theme } from '../hooks/useTheme'

type Props = {
  theme: Theme
  onToggle: () => void
}

/**
 * The two icons are stacked and cross-faded rather than swapped, so the button
 * never reflows and the change reads as one object turning over.
 */
export function ThemeToggle({ theme, onToggle }: Props) {
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={isDark ? 'Включить светлую тему' : 'Включить тёмную тему'}
      title={isDark ? 'Светлая тема' : 'Тёмная тема'}
      className="press grid h-9 w-9 place-items-center rounded-lg border border-line text-ink-muted hover:bg-raised hover:text-ink"
    >
      <span className="relative block h-[18px] w-[18px]">
        <Sun
          size={18}
          aria-hidden
          className="absolute inset-0 transition-[opacity,transform] duration-200 ease-out"
          style={{
            opacity: isDark ? 0 : 1,
            transform: isDark ? 'rotate(-90deg) scale(0.7)' : 'none',
          }}
        />
        <Moon
          size={18}
          aria-hidden
          className="absolute inset-0 transition-[opacity,transform] duration-200 ease-out"
          style={{
            opacity: isDark ? 1 : 0,
            transform: isDark ? 'none' : 'rotate(90deg) scale(0.7)',
          }}
        />
      </span>
    </button>
  )
}
