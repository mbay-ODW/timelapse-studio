import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtDate, fmtDateTime } from '../lib/format'

export type HistItem = [number, number] // [bucket-start-ms, count]

/**
 * Aktivitäts-Histogramm (B-5): Balken pro Tag/Stunde, optional Auswahl-Anteil überlagert.
 * Maus-Drag wählt einen Zeitraum → onRange(fromMs, toMs exklusiv).
 */
export function Histogram({ items, selected, sizeMs, onRange, height = 70, range }: {
  items: HistItem[]; selected?: Map<number, number>; sizeMs: number; height?: number
  onRange?: (from: number, to: number) => void; range?: [number, number] | null
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(600)
  const [drag, setDrag] = useState<[number, number] | null>(null)
  const [hover, setHover] = useState<{ x: number; text: string } | null>(null)

  useEffect(() => {
    const ro = new ResizeObserver(() => setW(wrap.current?.clientWidth ?? 600))
    if (wrap.current) ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  const { t0, t1, max } = useMemo(() => {
    if (!items.length) return { t0: 0, t1: 1, max: 1 }
    return { t0: items[0][0], t1: items[items.length - 1][0] + sizeMs, max: Math.max(...items.map((i) => i[1])) }
  }, [items, sizeMs])
  const xOf = (t: number) => ((t - t0) / (t1 - t0)) * w
  const tOf = (x: number) => t0 + (Math.min(Math.max(x, 0), w) / w) * (t1 - t0)

  useEffect(() => {
    const c = canvas.current
    if (!c) return
    const dpr = window.devicePixelRatio || 1
    c.width = w * dpr
    c.height = height * dpr
    const g = c.getContext('2d')!
    g.scale(dpr, dpr)
    g.clearRect(0, 0, w, height)
    const cs = getComputedStyle(c)
    const base = cs.getPropertyValue('--hist-bar').trim() || '#9aa3b2'
    const acc = cs.getPropertyValue('--accent').trim() || '#3b6fd8'
    const bw = Math.max(1, (sizeMs / (t1 - t0)) * w - (sizeMs / (t1 - t0)) * w * 0.15)
    for (const [t, n] of items) {
      const x = xOf(t)
      const h = (n / max) * (height - 4)
      g.fillStyle = selected ? base : acc
      g.globalAlpha = selected ? 0.45 : 0.85
      g.fillRect(x, height - h, bw, h)
      const s = selected?.get(t)
      if (s) {
        g.globalAlpha = 1
        g.fillStyle = acc
        const hs = (s / max) * (height - 4)
        g.fillRect(x, height - hs, bw, hs)
      }
    }
    g.globalAlpha = 1
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, selected, w, height, t0, t1, max, sizeMs])

  const snap = (t: number) => Math.floor(t / sizeMs) * sizeMs
  const shown = drag ? [Math.min(...drag), Math.max(...drag)] : range
  return (
    <div ref={wrap} className="hist" style={{ height }}
      onPointerDown={(e) => {
        if (!onRange) return
        const x = e.clientX - wrap.current!.getBoundingClientRect().left
        ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
        setDrag([tOf(x), tOf(x)])
      }}
      onPointerMove={(e) => {
        const x = e.clientX - wrap.current!.getBoundingClientRect().left
        const t = snap(tOf(x))
        const it = items.find((i) => i[0] === t)
        setHover({ x, text: `${sizeMs >= 86_400_000 ? fmtDate(t) : fmtDateTime(t).slice(0, 16)} · ${it ? it[1] : 0} Bilder${selected?.get(t) ? ` · ${selected.get(t)} ausgewählt` : ''}` })
        if (drag) setDrag([drag[0], tOf(x)])
      }}
      onPointerUp={() => {
        if (drag && onRange) {
          const a = snap(Math.min(...drag)), b = snap(Math.max(...drag)) + sizeMs
          if (b - a >= sizeMs) onRange(a, b)
        }
        setDrag(null)
      }}
      onPointerLeave={() => setHover(null)}>
      <canvas ref={canvas} style={{ width: '100%', height }} />
      {shown && <div className="hist-range" style={{ left: xOf(snap(shown[0])), width: Math.max(2, xOf(snap(shown[1]) + (drag ? sizeMs : 0)) - xOf(snap(shown[0]))) }} />}
      {hover && <div className="hist-tip" style={{ left: Math.min(hover.x, w - 180) }}>{hover.text}</div>}
    </div>
  )
}
