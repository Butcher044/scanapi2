/** @type {import('tailwindcss').Config} */

/* Every color resolves to a CSS variable from src/styles/tokens.css, so the
   theme swap happens in one place and components never name a raw hex. */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: token('page'),
        surface: token('surface'),
        raised: token('raised'),
        line: {
          DEFAULT: token('line'),
          strong: token('line-strong'),
        },
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          faint: token('ink-faint'),
        },
        brand: {
          DEFAULT: token('brand'),
          solid: token('brand-solid'),
          tint: token('brand-tint'),
          fg: token('on-brand'),
        },
        ok: {
          DEFAULT: token('ok'),
          tint: token('ok-tint'),
        },
        warn: {
          DEFAULT: token('warn'),
          tint: token('warn-tint'),
        },
        danger: {
          DEFAULT: token('danger'),
          tint: token('danger-tint'),
        },
        bank: {
          alfabank: token('bank-alfabank'),
          tbank: token('bank-tbank'),
          sber: token('bank-sber'),
          tochka: token('bank-tochka'),
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.23, 1, 0.32, 1)',
        'in-out': 'cubic-bezier(0.77, 0, 0.175, 1)',
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--c-ink) / 0.04), 0 1px 3px rgb(var(--c-ink) / 0.06)',
        raised: '0 4px 12px rgb(var(--c-ink) / 0.08), 0 1px 3px rgb(var(--c-ink) / 0.06)',
        pop: '0 12px 32px rgb(var(--c-ink) / 0.12), 0 2px 8px rgb(var(--c-ink) / 0.08)',
      },
      animation: {
        'fade-in': 'fadeIn 240ms cubic-bezier(0.23, 1, 0.32, 1) both',
        'slide-up': 'slideUp 240ms cubic-bezier(0.23, 1, 0.32, 1) both',
        'scale-in': 'scaleIn 180ms cubic-bezier(0.23, 1, 0.32, 1) both',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
        },
        /* Never from scale(0) — nothing in the real world appears from nothing. */
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.96)' },
        },
      },
    },
  },
  plugins: [],
}
