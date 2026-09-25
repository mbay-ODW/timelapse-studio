import { useEffect, useRef, useState } from 'react'
import { api, previewUrl } from '../lib/api'
import { fmtDateTime } from '../lib/format'

type Rect = { x: number; y: number; w: number; h: number } // normiert 0..1
const RATIOS: [string, number | null][] = [['frei', null], ['16:9', 16 / 9], ['9:16', 9 / 16], ['1:1', 1], ['4:3', 4 / 3]]

/** Crop-Rechteck per Maus auf einem Beispielbild der Auswahl festlegen (P-11). */
export function CropEditor({ projectId, initial, onSave, onClose }: {
  projectId: number; initial: Rect | null; onSave: (r: Rect | null) => void; onClose: () => void
}) {
  const [pos, setPos] = useState(0.5)
  const [sample, setSample] = useState<{ id: number; taken_ms: number } | null>(null)
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [rect, setRect] = useState<Rect>(initial ?? { x: 0.1, y: 0.1, w: 0.8, h: 0.8 })
  const [ratio, setRatio] = useState<number | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef<{ mode: string; sx: number; sy: number; r: Rect } | null>(null)

  useEffect(() => { api.get<{ id: number; taken_ms: number }>(`/api/projects/${projectId}/sample-image?position=${pos}`).then(setSample).catch(() => {}) }, [projectId, pos])

  // Seitenverhältnis in Pixeln des Quellbilds erzwingen
  const applyRatio = (r: Rect, rt: number | null, anchor: 'w' | 'h' = 'w'): Rect => {
    if (!rt || !nat) return r
    const k = nat.w / nat.h
    let { w, h } = r
    if (anchor === 'w') h = (w * k) / rt
    else w = (h * rt) / k
    if (h > 1) { h = 1; w = (h * rt) / k }
    if (w > 1) { w = 1; h = (w * k) / rt }
    return { x: Math.min(r.x, 1 - w), y: Math.min(r.y, 1 - h), w, h }
  }

  const onDown = (mode: string) => (e: React.PointerEvent) => {
    e.stopPropagation()
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { mode, sx: e.clientX, sy: e.clientY, r: rect }
  }
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d || !box.current) return
    const b = box.current.getBoundingClientRect()
    const dx = (e.clientX - d.sx) / b.width, dy = (e.clientY - d.sy) / b.height
    let { x, y, w, h } = d.r
    if (d.mode === 'move') {
      x = Math.min(Math.max(0, x + dx), 1 - w); y = Math.min(Math.max(0, y + dy), 1 - h)
    } else {
      if (d.mode.includes('e')) w = Math.min(1 - x, Math.max(0.02, w + dx))
      if (d.mode.includes('s')) h = Math.min(1 - y, Math.max(0.02, h + dy))
      if (d.mode.includes('w')) { const nx = Math.min(x + w - 0.02, Math.max(0, x + dx)); w += x - nx; x = nx }
      if (d.mode.includes('n')) { const ny = Math.min(y + h - 0.02, Math.max(0, y + dy)); h += y - ny; y = ny }
    }
    setRect(applyRatio({ x, y, w, h }, ratio, d.mode === 'n' || d.mode === 's' ? 'h' : 'w'))
  }

  const px = nat ? `${Math.round(rect.w * nat.w)} × ${Math.round(rect.h * nat.h)} px` : ''
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal stack" style={{ maxWidth: 1000 }}>
        <div className="row wrap">
          <h2 className="grow" style={{ margin: 0 }}>Zuschnitt festlegen</h2>
          <div className="seg">{RATIOS.map(([l, r]) => (
            <button key={l} className={ratio === r ? 'active' : ''} onClick={() => { setRatio(r); setRect(applyRatio(rect, r)) }}>{l}</button>
          ))}</div>
        </div>
        <div ref={box} className="crop-box" onPointerMove={onMove} onPointerUp={() => { drag.current = null }}>
          {sample && <img src={previewUrl(sample.id)} alt="" draggable={false} onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />}
          <div className="crop-rect" style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.w * 100}%`, height: `${rect.h * 100}%` }}
            onPointerDown={onDown('move')}>
            {['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].map((m) => <span key={m} className={`crop-h ${m}`} onPointerDown={onDown(m)} />)}
          </div>
        </div>
        <div className="row wrap small">
          <span className="muted">Beispielbild</span>
          <input type="range" className="grow" min={0} max={1} step={0.001} value={pos} onChange={(e) => setPos(Number(e.target.value))} />
          <span>{sample ? fmtDateTime(sample.taken_ms) : ''}</span>
          <span className="badge">{px}</span>
        </div>
        <div className="row">
          <button className="ghost" onClick={() => onSave(null)}>Zuschnitt entfernen</button>
          <div className="spacer" />
          <button onClick={onClose}>Abbrechen</button>
          <button className="primary" onClick={() => onSave({ x: +rect.x.toFixed(5), y: +rect.y.toFixed(5), w: +rect.w.toFixed(5), h: +rect.h.toFixed(5) })}>Übernehmen</button>
        </div>
      </div>
    </div>
  )
}
