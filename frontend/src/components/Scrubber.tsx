import { useMemo, useRef, useState } from 'react'
import { dayToMs, fmtDateLong, fmtMonth } from '../lib/format'
import type { Bucket } from './TimelineGrid'

/** Rechte Zeitleiste wie bei Immich (B-2): Monatsmarken, Hover-Datum, Klick/Drag springt. */
export function Scrubber({ buckets, currentDay, onJump }: {
  buckets: Bucket[]; currentDay?: string; onJump: (day: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ y: number; day: string } | null>(null)
  const dragging = useRef(false)
  // Position proportional zur Bildanzahl (entspricht grob der Scrollhöhe)
  const { marks, cum, total } = useMemo(() => {
    const cum: number[] = []
    let t = 0
    for (const b of buckets) { cum.push(t); t += b.count + 12 }
    const marks: { pos: number; label: string }[] = []
    let lastMonth = ''
    buckets.forEach((b, i) => {
      const m = b.day.slice(0, 7)
      if (m !== lastMonth) { marks.push({ pos: cum[i] / Math.max(t, 1), label: fmtMonth(dayToMs(b.day)) }); lastMonth = m }
    })
    return { marks, cum, total: Math.max(t, 1) }
  }, [buckets])

  const dayAt = (clientY: number) => {
    const r = ref.current!.getBoundingClientRect()
    const f = Math.min(1, Math.max(0, (clientY - r.top) / r.height)) * total
    let lo = 0, hi = cum.length - 1
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (cum[mid] <= f) lo = mid; else hi = mid - 1 }
    return { y: clientY - r.top, day: buckets[lo]?.day }
  }
  const curIdx = currentDay ? buckets.findIndex((b) => b.day === currentDay) : -1

  if (!buckets.length) return null
  return (
    <div ref={ref} className="scrubber"
      onPointerDown={(e) => { dragging.current = true; (e.target as HTMLElement).setPointerCapture(e.pointerId); const h = dayAt(e.clientY); if (h.day) onJump(h.day) }}
      onPointerMove={(e) => { const h = dayAt(e.clientY); if (h.day) { setHover(h as { y: number; day: string }); if (dragging.current) onJump(h.day) } }}
      onPointerUp={() => { dragging.current = false }}
      onPointerLeave={() => { if (!dragging.current) setHover(null) }}>
      {marks.map((m) => <div key={m.label} className="scrubber-mark" style={{ top: `${m.pos * 100}%` }}>{m.label}</div>)}
      {curIdx >= 0 && <div className="scrubber-pos" style={{ top: `${(cum[curIdx] / total) * 100}%` }} />}
      {hover && <div className="scrubber-hover" style={{ top: hover.y }}>{fmtDateLong(dayToMs(hover.day))}</div>}
    </div>
  )
}
