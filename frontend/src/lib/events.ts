import { useEffect, useState } from 'react'

type Listener = (data: any) => void
const listeners: Record<string, Set<Listener>> = {}
const lastData: Record<string, any> = {}
let source: EventSource | null = null

function ensure() {
  if (source) return
  source = new EventSource('/api/events')
  for (const name of ['scan', 'jobs']) {
    source.addEventListener(name, (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      lastData[name] = data
      listeners[name]?.forEach((l) => l(data))
    })
  }
}

/** Live-Daten per SSE (R-3); eine Verbindung für die ganze App. */
export function useEvent<T>(name: 'scan' | 'jobs'): T | undefined {
  const [data, setData] = useState<T | undefined>(lastData[name])
  useEffect(() => {
    ensure()
    const l: Listener = (d) => setData(d)
    ;(listeners[name] ??= new Set()).add(l)
    return () => { listeners[name].delete(l) }
  }, [name])
  return data
}
