import { useState } from 'react'

/** Kleine UI-Vorlieben im localStorage (Zoom, Tabs …) – robust gegen gesperrten Speicher. */
export function useLocal<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try { const s = localStorage.getItem('tls:' + key); return s != null ? JSON.parse(s) : initial } catch { return initial }
  })
  const set = (nv: T) => { setV(nv); try { localStorage.setItem('tls:' + key, JSON.stringify(nv)) } catch { /* ignore */ } }
  return [v, set]
}
