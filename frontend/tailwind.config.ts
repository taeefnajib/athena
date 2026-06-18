import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        card: 'var(--card)',
        card2: 'var(--card2)',
        border: 'var(--border)',
        border2: 'var(--border2)',
        text: 'var(--text)',
        dim: 'var(--text-dim)',
        muted: 'var(--text-muted)',
        accent: 'var(--accent)',
        accent2: 'var(--accent2)',
        success: 'var(--success)',
        warning: 'var(--warning)',
        error: 'var(--error)',
        running: 'var(--running)',
      },
      fontFamily: {
        sans: ['var(--font)'],
        mono: ['var(--mono)'],
      },
    },
  },
  plugins: [],
} satisfies Config
