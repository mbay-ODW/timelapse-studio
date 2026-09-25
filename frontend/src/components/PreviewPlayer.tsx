import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { previews, thumbs, type BatchLoader } from '../lib/batchLoader'
import { fmtDateTime, fmtNum } from '../lib/format'
import type { VideoParams } from '../lib/types'

const PAGE = 20000
const AHEAD = 180   // Frames vorausladen (V-2)
const BEHIND = 30
const ASPECTS: Record<string, number> = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:3': 4 / 3 }
const WD = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
const MON = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']

/** strftime-Teilmenge für die Overlay-Vorschau (Server nutzt Python-strftime). */
export function strftime(fmt: string, ms: number): string {
  const d = new Date(ms)
  const p = (n: number, l = 2) => String(n).padStart(l, '0')
  const map: Record<string, string> = {
    '%d': p(d.getUTCDate()), '%m': p(d.getUTCMonth() + 1), '%Y': String(d.getUTCFullYear()), '%y': p(d.getUTCFullYear() % 100),
    '%H': p(d.getUTCHours()), '%M': p(d.getUTCMinutes()), '%S': p(d.getUTCSeconds()), '%a': WD[d.getUTCDay()],
    '%b': MON[d.getUTCMonth()], '%j': p(Math.floor((ms - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86_400_000) + 1, 3), '%%': '%',
  }
  return fmt.replace(/%[dmYyHMSabj%]/g, (t) => map[t] ?? t)
}

export function PreviewPlayer({ projectId, evalKey, params, total }: {
  projectId: number; evalKey: string; params: VideoParams; total: number
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const ids = useRef<Int32Array>(new Int32Array(0))
  const times = useRef<Float64Array>(new Float64Array(0))
  const loadedPages = useRef(new Set<number>())
  const images = useRef(new Map<number, HTMLImageElement>())
  const [count, setCount] = useState(total)
  const [idx, setIdx] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [quality, setQuality] = useState<'thumb' | 'proxy'>('thumb')
  const [buffering, setBuffering] = useState(false)
  const [, setPagesVersion] = useState(0)
  const idxRef = useRef(0)
  const lastPreload = useRef(0)
  const loader: BatchLoader = quality === 'proxy' ? previews : thumbs

  // Frame-Liste bei neuer Auswertung neu laden
  useEffect(() => {
    ids.current = new Int32Array(total)
    times.current = new Float64Array(total)
    loadedPages.current = new Set()
    images.current = new Map()
    setCount(total)
    setIdx((i) => Math.min(i, Math.max(0, total - 1)))
    setPlaying(false)
  }, [evalKey, total])

  const ensurePage = useCallback(async (page: number) => {
    if (loadedPages.current.has(page)) return
    loadedPages.current.add(page)
    try {
      const r = await api.get<{ items: [number, number][] }>(`/api/projects/${projectId}/frames?offset=${page * PAGE}&limit=${PAGE}`)
      r.items.forEach(([id, t], k) => { ids.current[page * PAGE + k] = id; times.current[page * PAGE + k] = t })
      setPagesVersion((v) => v + 1)
    } catch { loadedPages.current.delete(page) }
  }, [projectId])

  const frameId = (i: number) => ids.current[i] || 0

  // Vorladen: Seitenliste + Bilder im Fenster
  const preload = useCallback(async (center: number) => {
    const lo = Math.max(0, center - BEHIND), hi = Math.min(count - 1, center + AHEAD)
    await Promise.all([...new Set([Math.floor(lo / PAGE), Math.floor(hi / PAGE)])].map(ensurePage))
    const want: number[] = []
    for (let i = lo; i <= hi; i++) { const id = frameId(i); if (id && !images.current.has(id)) want.push(id) }
    for (const id of want) {
      loader.get(id).then((url) => {
        if (!url || images.current.has(id)) return
        const im = new Image()
        im.src = url
        im.decode().then(() => images.current.set(id, im)).catch(() => {})
      })
    }
    // Speicher begrenzen
    if (images.current.size > AHEAD + BEHIND + 200) {
      const keep = new Set<number>()
      for (let i = lo; i <= hi; i++) keep.add(frameId(i))
      for (const k of images.current.keys()) if (!keep.has(k)) images.current.delete(k)
    }
  }, [count, ensurePage, loader])

  useEffect(() => { images.current = new Map() }, [quality])

  // Zeichnen inkl. Näherung von Crop/Rotation/Spiegeln/Overlay
  const draw = useCallback((i: number) => {
    const c = canvas.current
    if (!c) return false
    const im = images.current.get(frameId(i))
    if (!im) return false
    const g = c.getContext('2d')!
    const sw = im.naturalWidth, sh = im.naturalHeight
    let cx = 0, cy = 0, cw = sw, ch = sh
    if (params.crop) {
      cx = params.crop.x * sw; cy = params.crop.y * sh; cw = params.crop.w * sw; ch = params.crop.h * sh
    } else if (ASPECTS[params.aspect]) {
      let target = ASPECTS[params.aspect]
      if (params.rotate === 90 || params.rotate === 270) target = 1 / target
      if (cw / ch > target) { const nw = ch * target; cx = (cw - nw) / 2; cw = nw } else { const nh = cw / target; cy = (ch - nh) / 2; ch = nh }
    }
    const rot = params.rotate === 90 || params.rotate === 270
    const ow = rot ? ch : cw, oh = rot ? cw : ch
    const maxW = c.parentElement!.clientWidth, maxH = Math.min(window.innerHeight * 0.55, 620)
    const s = Math.min(maxW / ow, maxH / oh)
    const W = Math.round(ow * s), H = Math.round(oh * s)
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H }
    g.save()
    g.translate(W / 2, H / 2)
    g.rotate((params.rotate * Math.PI) / 180)
    g.scale(params.flip_h ? -1 : 1, params.flip_v ? -1 : 1)
    const dw = (rot ? H : W), dh = (rot ? W : H)
    g.drawImage(im, cx, cy, cw, ch, -dw / 2, -dh / 2, dw, dh)
    g.restore()
    if (params.overlay.enabled && times.current[i]) {
      const fs = Math.max(8, H * params.overlay.size / 100)
      const txt = strftime(params.overlay.format, times.current[i])
      g.font = `${fs}px system-ui, sans-serif`
      const tw = g.measureText(txt).width, pad = fs / 2
      const pos = params.overlay.position
      const x = pos.endsWith('l') ? pad : pos.endsWith('r') ? W - tw - pad : (W - tw) / 2
      const y = pos.startsWith('t') ? pad + fs : H - pad
      if (params.overlay.box) { g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(x - fs / 4, y - fs, tw + fs / 2, fs * 1.3) }
      g.fillStyle = '#fff'
      g.fillText(txt, x, y - fs * 0.12)
    }
    return true
  }, [params])

  // Abspielschleife (rAF): hält bei fehlenden Frames an statt zu springen
  useEffect(() => {
    if (!playing) return
    let raf = 0, last = performance.now(), acc = 0
    const tick = (now: number) => {
      acc += ((now - last) / 1000) * params.fps * speed
      last = now
      let i = idxRef.current
      while (acc >= 1 && i < count - 1) {
        if (!images.current.has(frameId(i + 1))) { acc = 0; break }
        i++; acc--
      }
      const waiting = i < count - 1 && !images.current.has(frameId(i + 1))
      setBuffering(waiting)
      if (i !== idxRef.current) { idxRef.current = i; setIdx(i); draw(i) }
      if ((i % 20 === 0 || waiting) && now - lastPreload.current > 250) { lastPreload.current = now; void preload(i) }
      if (i >= count - 1) { setPlaying(false); return }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed, params.fps, count, draw, preload])

  // Standbild bei Positions-/Parameterwechsel
  useEffect(() => {
    idxRef.current = idx
    if (playing) return
    let alive = true
    const tryDraw = async () => {
      await preload(idx)
      for (let k = 0; k < 40 && alive; k++) { if (draw(idx)) return; await new Promise((r) => setTimeout(r, 75)) }
    }
    void tryDraw()
    return () => { alive = false }
  }, [idx, playing, draw, preload, evalKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input,textarea,select')) return
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
      else if (e.key === '.') setIdx((i) => Math.min(count - 1, i + 1))
      else if (e.key === ',') setIdx((i) => Math.max(0, i - 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count])

  if (count === 0) return <div className="card empty">Keine Bilder ausgewählt.</div>
  const pos = idx / params.fps
  return (
    <div className="card player">
      <div className="player-stage">
        <canvas ref={canvas} />
        {buffering && <span className="player-buffer">puffert…</span>}
      </div>
      <div className="row wrap player-controls">
        <button className="icon" onClick={() => setIdx(Math.max(0, idx - 1))} title="Frame zurück ( , )">⏮</button>
        <button className="primary" style={{ minWidth: 70 }} onClick={() => { if (idx >= count - 1) setIdx(0); setPlaying(!playing) }}>{playing ? '❚❚ Pause' : '▶ Play'}</button>
        <button className="icon" onClick={() => setIdx(Math.min(count - 1, idx + 1))} title="Frame vor ( . )">⏭</button>
        <input type="range" className="grow" min={0} max={count - 1} value={idx} onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)) }} />
        <span className="mono">{Math.floor(pos / 60)}:{String(Math.floor(pos % 60)).padStart(2, '0')}</span>
      </div>
      <div className="row wrap small">
        <span className="muted">Frame {fmtNum(idx + 1)} / {fmtNum(count)}</span>
        {times.current[idx] ? <span>{fmtDateTime(times.current[idx])}</span> : null}
        <div className="spacer" />
        <label className="row">Tempo
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {[0.25, 0.5, 1, 2, 4].map((s) => <option key={s} value={s}>{s}×</option>)}
          </select></label>
        <label className="row">Qualität
          <select value={quality} onChange={(e) => setQuality(e.target.value as 'thumb' | 'proxy')}>
            <option value="thumb">Thumbnail (schnell)</option><option value="proxy">Proxy 960 px</option>
          </select></label>
      </div>
      <div className="muted small">Browser-Vorschau ohne Rendern · {params.fps} fps · Zuschnitt, Drehung und Zeitstempel angenähert; Deflicker/Blending nur im Schnell-Preview.</div>
    </div>
  )
}
