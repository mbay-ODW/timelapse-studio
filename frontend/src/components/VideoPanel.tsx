import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { fmtBytes, fmtDuration, fmtNum } from '../lib/format'
import type { Evaluation, Rule, Suggestion, VideoParams } from '../lib/types'
import { toast, toastError } from './Toast'

type Preset = { id: number; name: string; params: Partial<VideoParams> }

const FPS_CHOICES = [12, 24, 25, 30, 50, 60]
const RES = [['source', 'Original'], ['2160', '4K (2160p)'], ['1440', '1440p'], ['1080', '1080p'], ['720', '720p'], ['custom', 'Benutzerdefiniert']]
const ASPECT = [['original', 'Original'], ['16:9', '16:9'], ['9:16', '9:16 (Hochformat)'], ['1:1', '1:1'], ['4:3', '4:3']]
const POS = [['tl', 'oben links'], ['tc', 'oben Mitte'], ['tr', 'oben rechts'], ['bl', 'unten links'], ['bc', 'unten Mitte'], ['br', 'unten rechts']]
const QUAL = [['small', 'Klein'], ['standard', 'Standard'], ['high', 'Hoch'], ['max', 'Maximum']]

function parseLen(s: string): number | null {
  const m = s.trim().match(/^(?:(\d+):)?(\d+)(?:[.,](\d+))?$/)
  if (!m) return null
  return (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]) + (m[3] ? Number('0.' + m[3]) : 0)
}
const fmtLen = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

export function VideoPanel({ params, onChange, evaluation, rules, onRules, onOpenCrop, onRender }: {
  params: VideoParams; onChange: (p: Partial<VideoParams>) => void; evaluation: Evaluation | null
  rules: Rule[]; onRules: (r: Rule[]) => void; onOpenCrop: () => void
  onRender: (kind: 'render' | 'preview', range?: { start?: number; end?: number; seconds?: number }) => void
}) {
  const v = evaluation?.video
  const [lenText, setLenText] = useState(fmtLen(params.target_length_s))
  const [presets, setPresets] = useState<Preset[]>([])
  const [expert, setExpert] = useState(params.expert.enabled)
  const [prevRange, setPrevRange] = useState<'all' | '30s' | 'frames'>('30s')
  const [pr, setPr] = useState({ start: 0, end: 1000 })
  useEffect(() => { api.get<Preset[]>('/api/presets').then(setPresets).catch(() => {}) }, [])
  useEffect(() => { setLenText(fmtLen(params.target_length_s)) }, [params.target_length_s])

  const applySuggestion = (s: Suggestion) => {
    const base = rules.filter((r) => !r.params.auto)
    if (s.kind === 'fps') { onChange({ fps: s.fps }); onRules(base); return }
    if (s.kind === 'nth') onRules([...base, { type: 'nth', enabled: true, params: { n: s.n, offset: 0, auto: true } }])
    if (s.kind === 'limit') onRules([...base, { type: 'limit', enabled: true, params: { n: s.limit, auto: true } }])
    onChange({ fps: s.fps })
    toast('Vorschlag übernommen')
  }
  const savePreset = async () => {
    const name = prompt('Name des Presets')
    if (!name) return
    try { setPresets(await api.post<Preset[]>('/api/presets', { name, params })); toast('Preset gespeichert') } catch (e) { toastError(e) }
  }
  const applyPreset = (id: number) => {
    const p = presets.find((x) => x.id === id)
    if (p) { onChange(p.params); toast(`Preset „${p.name}“ angewendet`) }
  }
  const uploadAudio = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    try {
      const r = await fetch('/api/audio', { method: 'POST', body: fd })
      if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText)
      const j = await r.json()
      onChange({ audio: { ...params.audio, file: j.file, name: j.name } })
    } catch (e) { toastError(e) }
  }
  const hasAuto = rules.some((r) => r.params.auto)

  return (
    <div className="video-panel">
      {/* ---------- Zeit */}
      <section className="card stack">
        <div className="row wrap">
          <h2 className="grow" style={{ margin: 0 }}>Zeit</h2>
          <div className="seg">
            <button className={params.mode === 'fps' ? 'active' : ''} onClick={() => onChange({ mode: 'fps' })}>fps fix</button>
            <button className={params.mode === 'length' ? 'active' : ''} onClick={() => onChange({ mode: 'length' })}>Ziellänge fix</button>
          </div>
        </div>
        <div className="time-summary">
          <div><span className="big">{v ? fmtNum(v.frames) : '…'}</span><span className="muted small">Frames</span></div>
          <div className="op">÷</div>
          <div><span className="big">{params.fps}</span><span className="muted small">fps</span></div>
          <div className="op">=</div>
          <div><span className="big">{v ? fmtDuration(v.total_s) : '…'}</span><span className="muted small">Videolänge{v && v.extra_s > 0 ? ` (inkl. ${v.extra_s} s extra)` : ''}</span></div>
        </div>
        <div className="row wrap">
          <label className="field">fps
            <input type="number" min={0.1} max={240} step={0.5} value={params.fps} style={{ width: 90 }}
              onChange={(e) => { const x = e.target.valueAsNumber; if (x > 0) onChange({ fps: x }) }} /></label>
          <div className="seg" style={{ alignSelf: 'flex-end' }}>
            {FPS_CHOICES.map((f) => <button key={f} className={params.fps === f ? 'active' : ''} onClick={() => onChange({ fps: f })}>{f}</button>)}
          </div>
          {params.mode === 'length' && (
            <label className="field">Ziellänge (m:ss)
              <input value={lenText} style={{ width: 90 }} onChange={(e) => setLenText(e.target.value)}
                onBlur={() => { const s = parseLen(lenText); if (s && s > 0) onChange({ target_length_s: s }); else setLenText(fmtLen(params.target_length_s)) }}
                onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} /></label>
          )}
        </div>
        {v?.warnings.map((w) => <div key={w} className="badge warn" style={{ alignSelf: 'flex-start' }}>{w}</div>)}
        {params.mode === 'length' && v && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="muted small">Ausgangsbasis: {fmtNum(v.base_frames ?? 0)} Frames (ohne automatische Anpassungsregel). Vorschläge für {fmtLen(params.target_length_s)}:</span>
            {v.suggestions.map((s, i) => (
              <div key={i} className="suggestion">
                <div className="grow">
                  <div>{s.label}</div>
                  <div className="muted small">{fmtNum(s.frames)} Frames · {fmtDuration(s.total_s)}{s.exact ? ' · exakt' : ''}{s.notes.length ? ' · ' + s.notes.join(' ') : ''}</div>
                </div>
                {s.kind !== 'info' && <button onClick={() => applySuggestion(s)}>Übernehmen</button>}
              </div>
            ))}
            {hasAuto && <button className="ghost small" style={{ alignSelf: 'flex-start' }} onClick={() => onRules(rules.filter((r) => !r.params.auto))}>automatische Regel entfernen</button>}
          </div>
        )}
        <div className="row wrap">
          <label className="field">erstes Bild halten (s)<input type="number" min={0} step={0.5} value={params.hold_first_s} style={{ width: 90 }} onChange={(e) => onChange({ hold_first_s: e.target.valueAsNumber || 0 })} /></label>
          <label className="field">letztes Bild halten (s)<input type="number" min={0} step={0.5} value={params.hold_last_s} style={{ width: 90 }} onChange={(e) => onChange({ hold_last_s: e.target.valueAsNumber || 0 })} /></label>
        </div>
      </section>

      {/* ---------- Bild */}
      <section className="card stack">
        <h2 style={{ margin: 0 }}>Bild</h2>
        <div className="row wrap">
          <label className="field">Auflösung
            <select value={params.resolution} onChange={(e) => onChange({ resolution: e.target.value })}>
              {RES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
          {params.resolution === 'custom' && <>
            <label className="field">Breite<input type="number" value={params.custom_w} style={{ width: 90 }} onChange={(e) => onChange({ custom_w: e.target.valueAsNumber })} /></label>
            <label className="field">Höhe<input type="number" value={params.custom_h} style={{ width: 90 }} onChange={(e) => onChange({ custom_h: e.target.valueAsNumber })} /></label>
          </>}
          <label className="field">Seitenverhältnis
            <select value={params.aspect} disabled={!!params.crop} onChange={(e) => onChange({ aspect: e.target.value })}>
              {ASPECT.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></label>
          <div className="field"><span>Zuschnitt</span>
            <div className="row">
              <button onClick={onOpenCrop}>{params.crop ? 'Crop bearbeiten' : 'Crop festlegen'}</button>
              {params.crop && <button className="ghost" onClick={() => onChange({ crop: null })}>✕</button>}
            </div></div>
        </div>
        <div className="row wrap">
          <div className="field"><span>Drehen</span>
            <div className="seg">{[0, 90, 180, 270].map((r) => <button key={r} className={params.rotate === r ? 'active' : ''} onClick={() => onChange({ rotate: r })}>{r}°</button>)}</div></div>
          <label className="row small" style={{ alignSelf: 'flex-end' }}><input type="checkbox" checked={params.flip_h} onChange={(e) => onChange({ flip_h: e.target.checked })} />horizontal spiegeln</label>
          <label className="row small" style={{ alignSelf: 'flex-end' }}><input type="checkbox" checked={params.flip_v} onChange={(e) => onChange({ flip_v: e.target.checked })} />vertikal spiegeln</label>
        </div>
        {v && <div className="muted small">Quelle {v.source_size.w}×{v.source_size.h} → Zuschnitt {v.geometry.crop.w}×{v.geometry.crop.h} → <b>Ausgabe {v.geometry.out.w}×{v.geometry.out.h}</b></div>}
      </section>

      {/* ---------- Qualität */}
      <section className="card stack">
        <h2 style={{ margin: 0 }}>Codec & Qualität</h2>
        <div className="row wrap">
          <label className="field">Codec
            <select value={params.codec} onChange={(e) => onChange({ codec: e.target.value as VideoParams['codec'] })}>
              <option value="h264">H.264 (kompatibel)</option><option value="h265">H.265 (kleiner)</option><option value="av1">AV1 (langsam)</option>
            </select></label>
          <div className="field"><span>Qualität</span>
            <div className="seg">{QUAL.map(([k, l]) => <button key={k} disabled={expert} className={params.quality === k ? 'active' : ''} onClick={() => onChange({ quality: k })}>{l}</button>)}</div></div>
          <label className="row small" style={{ alignSelf: 'flex-end' }}><input type="checkbox" checked={expert}
            onChange={(e) => { setExpert(e.target.checked); onChange({ expert: { ...params.expert, enabled: e.target.checked } }) }} />Expertenmodus</label>
        </div>
        {expert && (
          <div className="row wrap">
            <label className="field">CRF / QP<input type="number" min={0} max={63} value={params.expert.crf} style={{ width: 80 }} onChange={(e) => onChange({ expert: { ...params.expert, crf: e.target.valueAsNumber } })} /></label>
            <label className="field">Preset
              <select value={params.expert.preset} onChange={(e) => onChange({ expert: { ...params.expert, preset: e.target.value } })}>
                {['ultrafast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow'].map((x) => <option key={x}>{x}</option>)}
              </select></label>
            <label className="field">Bitrate kbit/s (0 = CRF)<input type="number" min={0} step={500} value={params.expert.bitrate_kbps} style={{ width: 110 }} onChange={(e) => onChange({ expert: { ...params.expert, bitrate_kbps: e.target.valueAsNumber || 0 } })} /></label>
          </div>
        )}
      </section>

      {/* ---------- Effekte */}
      <section className="card stack">
        <h2 style={{ margin: 0 }}>Effekte</h2>
        <div className="effect">
          <label className="row"><input type="checkbox" checked={params.deflicker.enabled} onChange={(e) => onChange({ deflicker: { ...params.deflicker, enabled: e.target.checked } })} /><b>Deflicker</b></label>
          {params.deflicker.enabled && <div className="row small grow"><span>Fenster</span>
            <input type="range" className="grow" min={2} max={60} value={params.deflicker.size} onChange={(e) => onChange({ deflicker: { ...params.deflicker, size: Number(e.target.value) } })} />
            <span style={{ width: 70 }}>{params.deflicker.size} Frames</span></div>}
        </div>
        <div className="effect">
          <label className="row"><input type="checkbox" checked={params.blend.enabled} onChange={(e) => onChange({ blend: { ...params.blend, enabled: e.target.checked } })} /><b>Frame-Blending</b></label>
          {params.blend.enabled && <div className="row small grow"><span>Überblenden</span>
            <input type="range" className="grow" min={2} max={10} value={params.blend.frames} onChange={(e) => onChange({ blend: { ...params.blend, frames: Number(e.target.value) } })} />
            <span style={{ width: 70 }}>{params.blend.frames} Frames</span></div>}
        </div>
        <div className="effect">
          <label className="row"><input type="checkbox" checked={params.overlay.enabled} onChange={(e) => onChange({ overlay: { ...params.overlay, enabled: e.target.checked } })} /><b>Zeitstempel</b></label>
          {params.overlay.enabled && <div className="row wrap grow">
            <label className="field">Format<input className="mono" value={params.overlay.format} style={{ width: 150 }} onChange={(e) => onChange({ overlay: { ...params.overlay, format: e.target.value } })} /></label>
            <label className="field">Position<select value={params.overlay.position} onChange={(e) => onChange({ overlay: { ...params.overlay, position: e.target.value } })}>{POS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
            <label className="field">Größe (% Höhe)<input type="number" min={1} max={20} step={0.5} value={params.overlay.size} style={{ width: 80 }} onChange={(e) => onChange({ overlay: { ...params.overlay, size: e.target.valueAsNumber } })} /></label>
            <label className="row small" style={{ alignSelf: 'flex-end' }}><input type="checkbox" checked={params.overlay.box} onChange={(e) => onChange({ overlay: { ...params.overlay, box: e.target.checked } })} />Hintergrund-Box</label>
          </div>}
        </div>
        <div className="row wrap">
          <label className="field grow">Titel (Anfang)<input value={params.title.text} placeholder="optional" onChange={(e) => onChange({ title: { ...params.title, text: e.target.value } })} /></label>
          <label className="field">Dauer (s)<input type="number" min={0} step={0.5} value={params.title.duration_s} style={{ width: 70 }} onChange={(e) => onChange({ title: { ...params.title, duration_s: e.target.valueAsNumber || 0 } })} /></label>
        </div>
        <div className="row wrap">
          <label className="field grow">Abspann (Ende)<input value={params.credits.text} placeholder="optional" onChange={(e) => onChange({ credits: { ...params.credits, text: e.target.value } })} /></label>
          <label className="field">Dauer (s)<input type="number" min={0} step={0.5} value={params.credits.duration_s} style={{ width: 70 }} onChange={(e) => onChange({ credits: { ...params.credits, duration_s: e.target.valueAsNumber || 0 } })} /></label>
        </div>
        <div className="row wrap">
          <label className="field">Fade-in (s)<input type="number" min={0} step={0.5} value={params.fade_in_s} style={{ width: 80 }} onChange={(e) => onChange({ fade_in_s: e.target.valueAsNumber || 0 })} /></label>
          <label className="field">Fade-out (s)<input type="number" min={0} step={0.5} value={params.fade_out_s} style={{ width: 80 }} onChange={(e) => onChange({ fade_out_s: e.target.valueAsNumber || 0 })} /></label>
        </div>
        <div className="row wrap">
          <div className="field grow"><span>Musik</span>
            <div className="row">
              {params.audio.file
                ? <><span className="badge accent">♪ {params.audio.name}</span><button className="ghost small" onClick={() => onChange({ audio: { ...params.audio, file: null, name: null } })}>entfernen</button></>
                : <label className="btn">Datei wählen…<input type="file" accept="audio/*" hidden onChange={(e) => e.target.files?.[0] && uploadAudio(e.target.files[0])} /></label>}
            </div></div>
          {params.audio.file && <label className="field">Fade-out (s)<input type="number" min={0} step={0.5} value={params.audio.fade_out_s} style={{ width: 80 }} onChange={(e) => onChange({ audio: { ...params.audio, fade_out_s: e.target.valueAsNumber || 0 } })} /></label>}
        </div>
      </section>

      {/* ---------- Presets */}
      <section className="card row wrap">
        <h2 style={{ margin: 0 }} className="grow">Presets</h2>
        <select defaultValue="" onChange={(e) => { if (e.target.value) applyPreset(Number(e.target.value)); e.target.value = '' }}>
          <option value="" disabled>Preset anwenden…</option>
          {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button onClick={savePreset}>Als Preset speichern</button>
      </section>

      {/* ---------- Rendern */}
      <section className="card stack render-box">
        <div className="row wrap">
          <div className="grow">
            <div><b>Geschätzt:</b> {v ? `${fmtBytes(v.estimate.size_bytes)} · Renderdauer ca. ${fmtDuration(v.estimate.render_s)}` : '…'}</div>
            <div className="muted small">Schätzung, wird mit jedem fertigen Render genauer.</div>
          </div>
          <button className="primary" disabled={!v || v.frames < 2} onClick={() => onRender('render')}>Video rendern</button>
        </div>
        <div className="row wrap">
          <span className="small muted">Schnell-Preview (480p):</span>
          <select value={prevRange} onChange={(e) => setPrevRange(e.target.value as typeof prevRange)}>
            <option value="30s">erste 30 s</option><option value="all">gesamt</option><option value="frames">Frames von–bis</option>
          </select>
          {prevRange === 'frames' && <>
            <input type="number" min={0} value={pr.start} style={{ width: 90 }} onChange={(e) => setPr({ ...pr, start: e.target.valueAsNumber || 0 })} />
            <span>–</span>
            <input type="number" min={1} value={pr.end} style={{ width: 90 }} onChange={(e) => setPr({ ...pr, end: e.target.valueAsNumber || 1 })} />
          </>}
          <button disabled={!v || v.frames < 1} onClick={() => onRender('preview', prevRange === '30s' ? { seconds: 30 } : prevRange === 'frames' ? pr : undefined)}>Schnell-Preview rendern</button>
        </div>
      </section>
    </div>
  )
}
