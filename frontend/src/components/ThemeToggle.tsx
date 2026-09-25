import { useEffect, useState } from 'react'

type Mode = 'auto' | 'light' | 'dark'
const KEY = 'tls-theme'

function read(): Mode {
  try { return (localStorage.getItem(KEY) as Mode) || 'auto' } catch { return 'auto' }
}

export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>(read)
  useEffect(() => {
    const el = document.documentElement
    if (mode === 'auto') el.removeAttribute('data-theme')
    else el.setAttribute('data-theme', mode)
    try { localStorage.setItem(KEY, mode) } catch { /* ignore */ }
  }, [mode])
  const next: Record<Mode, Mode> = { auto: 'dark', dark: 'light', light: 'auto' }
  const label: Record<Mode, string> = { auto: '◐', dark: '☾', light: '☀' }
  return (
    <button className="ghost icon" title={`Design: ${mode === 'auto' ? 'System' : mode === 'dark' ? 'Dunkel' : 'Hell'}`}
      onClick={() => setMode(next[mode])}>{label[mode]}</button>
  )
}
