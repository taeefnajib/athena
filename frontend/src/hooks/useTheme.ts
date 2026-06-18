import { useEffect } from 'react'
import { useUiStore } from '../store/uiStore'

export function useTheme() {
  const theme = useUiStore(s => s.theme)

  useEffect(() => {
    const html = document.documentElement
    if (theme === 'system') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      html.setAttribute('data-theme', prefersDark ? 'dark' : 'light')
    } else {
      html.setAttribute('data-theme', theme)
    }
  }, [theme])
}
