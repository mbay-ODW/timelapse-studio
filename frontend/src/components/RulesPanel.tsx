import { useState } from 'react'
import { fmtDate, fmtNum } from '../lib/format'
import type { Evaluation, Rule, Source } from '../lib/types'
import { MiniChart } from './MiniChart'

export const RULE_LABEL: Record<string, string> = {
  sources: 'Quellen', date_range: 'Datumsbereich', time_window: 'Tageszeit-Fenster', weekdays: 'Wochentage',
  nth: 'Jedes n-te Bild', interval: 'Ein Bild pro Intervall', limit: 'Auf N Bilder begrenzen',
  brightness: 'Helligkeit', dedupe: 'Standbilder überspringen', manual: 'Manuelle Markierungen', order: 'Reihenfolge',
}

const DEFAULTS: Record<string, Record<string, any>> = {
  sources: { source_ids: [] }, date_range: { mode: 'exclude', ranges: [{ from: '', to: '' }] }, time_window: { from: '07:00', to: '19:00' },
  weekdays: { days: [0, 1, 2, 3, 4] }, nth: { n: 10, offset: 0 },
  interval: { interval_s: 3600, strategy: 'first', at: '12:00' }, limit: { n: 1000 },
  brightness: { min: 40, max: 255 }, dedupe: { threshold: 3 }, manual: {}, order: { direction: 'desc' },
}
const ADD_ORDER = ['date_range', 'time_window', 'weekdays', 'brightness', 'interval', 'nth', 'limit', 'dedupe', 'sources', 'manual', 'order']
const DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']

export function RulesPanel({ rules, onChange, evaluation, sources, onClearMarks }: {
  rules: Rule[]; onChange: (r: Rule[]) => void; evaluation: Evaluation | null; sources: Source[]
  onClearMarks: () => void
}) {
  const [adding, setAdding] = useState(false)
  const update = (i: number, r: Rule) => onChange(rules.map((x, j) => (j === i ? r : x)))
  const move = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= rules.length) return
    const next = [...rules]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  const ev = evaluation
  return (
    <div className="rules-panel">
      <div className="result-box">
        <div className="result-count">{ev ? fmtNum(ev.count) : '…'}</div>
        <div className="muted small">Bilder ausgewählt aus {ev ? fmtNum(ev.total) : '…'}
          {ev?.first_ms != null && <><br />{fmtDate(ev.first_ms)} – {fmtDate(ev.last_ms!)} · {ev.days} Tage</>}
          {ev && <span title="Berechnungszeit"> · {ev.elapsed_ms} ms</span>}
        </div>
        {ev && <MiniChart data={ev.distribution} />}
      </div>

      {rules.map((r, i) => {
        const step = ev?.steps[i]
        return (
          <div key={r.id ?? `new-${i}`} className={'rule' + (r.enabled ? '' : ' disabled')}>
            <div className="rule-head">
              <input type="checkbox" checked={r.enabled} title="aktiv" onChange={(e) => update(i, { ...r, enabled: e.target.checked })} />
              <span className="grow rule-title">{i + 1}. {RULE_LABEL[r.type] ?? r.type}{r.params.auto && <span className="badge accent" style={{ marginLeft: 6 }}>auto</span>}</span>
              {step?.count != null && <span className="badge" title="Bilder nach dieser Regel">{fmtNum(step.count)}</span>}
              <button className="icon ghost" disabled={i === 0} onClick={() => move(i, -1)} title="nach oben">↑</button>
              <button className="icon ghost" disabled={i === rules.length - 1} onClick={() => move(i, 1)} title="nach unten">↓</button>
              <button className="icon ghost danger" onClick={() => onChange(rules.filter((_, j) => j !== i))} title="entfernen">✕</button>
            </div>
            {step?.error && <div className="error-box small">{step.error}</div>}
            <div className="rule-body">
              <RuleEditor rule={r} onChange={(nr) => update(i, nr)} sources={sources} evaluation={ev} onClearMarks={onClearMarks} />
            </div>
          </div>
        )
      })}

      <div style={{ position: 'relative' }}>
        <button onClick={() => setAdding(!adding)} style={{ width: '100%' }}>+ Regel hinzufügen</button>
        {adding && (
          <div className="popover" style={{ left: 0, right: 0, minWidth: 0 }}>
            {ADD_ORDER.map((t) => (
              <button key={t} className="ghost" style={{ width: '100%', justifyContent: 'flex-start' }}
                onClick={() => { onChange([...rules, { type: t, enabled: true, params: structuredClone(DEFAULTS[t]) }]); setAdding(false) }}>
                {RULE_LABEL[t]}
              </button>
            ))}
          </div>
        )}
      </div>
      <p className="muted small">Regeln wirken nacheinander von oben nach unten. Änderungen werden automatisch gespeichert.</p>
    </div>
  )
}

function Num({ value, onChange, min, max, step, style }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; style?: React.CSSProperties
}) {
  return <input type="number" value={Number.isFinite(value) ? value : ''} min={min} max={max} step={step} style={{ width: 90, ...style }}
    onChange={(e) => { const v = e.target.valueAsNumber; if (!Number.isNaN(v)) onChange(v) }} />
}

function RuleEditor({ rule, onChange, sources, evaluation, onClearMarks }: {
  rule: Rule; onChange: (r: Rule) => void; sources: Source[]; evaluation: Evaluation | null; onClearMarks: () => void
}) {
  const p = rule.params
  const set = (patch: Record<string, any>) => onChange({ ...rule, params: { ...p, ...patch } })
  switch (rule.type) {
    case 'sources': {
      const ids: number[] = p.source_ids ?? []
      return (
        <div className="stack" style={{ gap: 4 }}>
          {sources.filter((s) => s.enabled).map((s) => (
            <label key={s.id} className="row small">
              <input type="checkbox" checked={ids.includes(s.id)}
                onChange={(e) => set({ source_ids: e.target.checked ? [...ids, s.id] : ids.filter((x) => x !== s.id) })} />
              {s.display_name} <span className="muted">({fmtNum(s.image_count)})</span>
            </label>
          ))}
          {ids.length === 0 && <span className="muted small">keine gewählt = alle aktiven Quellen</span>}
        </div>
      )
    }
    case 'date_range': {
      // alte Form {from, to} → ein Zeitraum
      const ranges: { from: string; to: string }[] = p.ranges ?? [{ from: p.from ?? '', to: p.to ?? '' }]
      const mode = p.mode ?? 'include'
      const setRanges = (r: typeof ranges) => onChange({ ...rule, params: { mode, ranges: r } })
      return (
        <div className="stack" style={{ gap: 6 }}>
          <div className="seg">
            <button className={mode === 'include' ? 'active' : ''} onClick={() => onChange({ ...rule, params: { mode: 'include', ranges } })}>nur diese behalten</button>
            <button className={mode === 'exclude' ? 'active' : ''} onClick={() => onChange({ ...rule, params: { mode: 'exclude', ranges } })}>diese ausschließen</button>
          </div>
          {ranges.map((r, k) => {
            const withTime = r.from.includes('T') || r.to.includes('T')
            const type = withTime ? 'datetime-local' : 'date'
            const upd = (patch: Partial<typeof r>) => setRanges(ranges.map((x, j) => (j === k ? { ...x, ...patch } : x)))
            return (
              <div key={k} className="row wrap range-row">
                <input type={type} value={r.from} title="von" onChange={(e) => upd({ from: e.target.value })} />
                <span className="muted">–</span>
                <input type={type} value={r.to} title={withTime ? 'bis (exklusiv)' : 'bis (inklusive)'} onChange={(e) => upd({ to: e.target.value })} />
                {withTime && <button className="ghost small" title="Uhrzeit entfernen" onClick={() => upd({ from: r.from.slice(0, 10), to: r.to.slice(0, 10) })}>nur Datum</button>}
                <button className="icon ghost" title="Zeitraum entfernen" disabled={ranges.length === 1} onClick={() => setRanges(ranges.filter((_, j) => j !== k))}>✕</button>
              </div>
            )
          })}
          <button className="ghost small" style={{ alignSelf: 'flex-start' }} onClick={() => setRanges([...ranges, { from: '', to: '' }])}>+ weiterer Zeitraum</button>
          <span className="muted small">Enddatum zählt mit. Tipp: im Histogramm einen Bereich ziehen.</span>
        </div>
      )
    }
    case 'time_window':
      return (
        <div className="row wrap">
          <label className="field">von<input type="time" value={p.from ?? ''} onChange={(e) => set({ from: e.target.value })} /></label>
          <label className="field">bis (exkl.)<input type="time" value={p.to ?? ''} onChange={(e) => set({ to: e.target.value })} /></label>
          {p.from > p.to && <span className="muted small">über Mitternacht</span>}
        </div>
      )
    case 'weekdays': {
      const days: number[] = p.days ?? []
      return (
        <div className="seg">
          {DAYS.map((d, i) => (
            <button key={d} className={days.includes(i) ? 'active' : ''}
              onClick={() => set({ days: days.includes(i) ? days.filter((x) => x !== i) : [...days, i].sort() })}>{d}</button>
          ))}
        </div>
      )
    }
    case 'nth':
      return (
        <div className="row wrap">
          <label className="field">jedes n-te<Num value={p.n} min={1} onChange={(v) => set({ n: Math.max(1, Math.round(v)) })} /></label>
          <label className="field">Offset<Num value={p.offset ?? 0} min={0} onChange={(v) => set({ offset: Math.max(0, Math.round(v)) })} /></label>
          <SlowmoEditor rule={rule} onChange={onChange} valueKey="n" />
        </div>
      )
    case 'interval': {
      const s = p.interval_s ?? 3600
      const unit = s % 86400 === 0 ? 86400 : s % 3600 === 0 ? 3600 : 60
      return (
        <div className="stack" style={{ gap: 6 }}>
          <div className="row wrap">
            <label className="field">Intervall<Num value={s / unit} min={1} onChange={(v) => set({ interval_s: Math.max(1, Math.round(v)) * unit })} /></label>
            <label className="field">&nbsp;
              <select value={unit} onChange={(e) => set({ interval_s: Math.max(1, Math.round(s / unit)) * Number(e.target.value) })}>
                <option value={60}>Minuten</option><option value={3600}>Stunden</option><option value={86400}>Tage</option>
              </select>
            </label>
          </div>
          <div className="row wrap">
            <label className="field">Strategie
              <select value={p.strategy ?? 'first'} onChange={(e) => set({ strategy: e.target.value })}>
                <option value="first">erstes Bild</option>
                <option value="nearest">nächstes zu Uhrzeit</option>
                <option value="brightest">hellstes</option>
                <option value="median">mittlere Helligkeit (Median)</option>
              </select>
            </label>
            {p.strategy === 'nearest' && <label className="field">Uhrzeit<input type="time" value={p.at ?? '12:00'} onChange={(e) => set({ at: e.target.value })} /></label>}
          </div>
          <SlowmoEditor rule={rule} onChange={onChange} valueKey="interval_s" />
        </div>
      )
    }
    case 'limit':
      return <label className="field">max. Anzahl, gleichmäßig über die Zeit<Num value={p.n} min={2} onChange={(v) => set({ n: Math.max(2, Math.round(v)) })} /></label>
    case 'brightness':
      return (
        <div className="stack" style={{ gap: 4 }}>
          <div className="row small"><span style={{ width: 30 }}>min</span>
            <input type="range" className="grow" min={0} max={255} value={p.min ?? 0} onChange={(e) => set({ min: Number(e.target.value) })} />
            <span style={{ width: 30, textAlign: 'right' }}>{p.min ?? 0}</span></div>
          <div className="row small"><span style={{ width: 30 }}>max</span>
            <input type="range" className="grow" min={0} max={255} value={p.max ?? 255} onChange={(e) => set({ max: Number(e.target.value) })} />
            <span style={{ width: 30, textAlign: 'right' }}>{p.max ?? 255}</span></div>
          <span className="muted small">0 = schwarz, 255 = weiß. Nachtbilder liegen meist unter 40.</span>
        </div>
      )
    case 'dedupe':
      return (
        <div className="row small">
          <span>Schwelle</span>
          <input type="range" className="grow" min={0} max={16} value={p.threshold ?? 3} onChange={(e) => set({ threshold: Number(e.target.value) })} />
          <span style={{ width: 24, textAlign: 'right' }}>{p.threshold ?? 3}</span>
        </div>
      )
    case 'manual':
      return (
        <div className="row wrap small">
          <span>{evaluation?.marks.include ?? 0} eingeschlossen · {evaluation?.marks.exclude ?? 0} ausgeschlossen</span>
          <button className="ghost small" onClick={() => { if (confirm('Alle manuellen Markierungen löschen?')) onClearMarks() }}>alle löschen</button>
        </div>
      )
    case 'order':
      return (
        <select value={p.direction ?? 'asc'} onChange={(e) => set({ direction: e.target.value })}>
          <option value="asc">chronologisch</option><option value="desc">umgekehrt</option>
        </select>
      )
    default:
      return null
  }
}

type Zone = { from: string; to: string; n?: number; interval_s?: number }

const fmtIv = (sec: number) => sec % 86400 === 0 ? `${sec / 86400} Tag(e)` : sec % 3600 === 0 ? `${sec / 3600} h` : `${Math.round(sec / 60)} min`

/** Zeitlupen-Bereiche: im Zeitraum mehr Bilder behalten → läuft bei konstanten fps langsamer ab. */
function SlowmoEditor({ rule, onChange, valueKey }: { rule: Rule; onChange: (r: Rule) => void; valueKey: 'n' | 'interval_s' }) {
  const zones: Zone[] = rule.params.slowmo ?? []
  const base: number = rule.params[valueKey] ?? (valueKey === 'n' ? 1 : 3600)
  const setZones = (z: Zone[]) => onChange({ ...rule, params: { ...rule.params, slowmo: z } })
  const upd = (k: number, patch: Partial<Zone>) => setZones(zones.map((z, j) => (j === k ? { ...z, ...patch } : z)))
  const def = valueKey === 'n' ? Math.max(1, Math.round(base / 5)) : Math.max(60, Math.round(base / 5 / 60) * 60)
  return (
    <div className="slowmo" style={{ flexBasis: '100%' }}>
      <div className="row"><b className="small grow">Zeitlupe</b>
        <button className="ghost small" onClick={() => setZones([...zones, { from: '', to: '', [valueKey]: def }])}>+ Bereich</button></div>
      {zones.length === 0 && <div className="muted small">Mehr Bilder in einem Zeitraum → läuft dort langsamer. Auch per Ziehen im Histogramm.</div>}
      {zones.map((z, k) => {
        const withTime = z.from.includes('T') || z.to.includes('T')
        const type = withTime ? 'datetime-local' : 'date'
        const v = z[valueKey] ?? def
        const factor = base / Math.max(v, 1)
        return (
          <div key={k} className="stack slowmo-zone">
            <div className="row range-row">
              <input type={type} value={z.from} title="von" onChange={(e) => upd(k, { from: e.target.value })} />
              <span className="muted">–</span>
              <input type={type} value={z.to} title={withTime ? 'bis (exklusiv)' : 'bis (inklusive)'} onChange={(e) => upd(k, { to: e.target.value })} />
              <button className="icon ghost" title="Bereich entfernen" onClick={() => setZones(zones.filter((_, j) => j !== k))}>✕</button>
            </div>
            <div className="row small">
              {valueKey === 'n'
                ? <label className="row">jedes<Num value={v} min={1} style={{ width: 64 }} onChange={(x) => upd(k, { n: Math.max(1, Math.round(x)) })} />. Bild</label>
                : <label className="row">1 Bild pro
                    <select value={v} onChange={(e) => upd(k, { interval_s: Number(e.target.value) })}>
                      {[...new Set([60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, v])].sort((a, b) => a - b)
                        .filter((x) => x <= base).map((x) => <option key={x} value={x}>{fmtIv(x)}</option>)}
                    </select></label>}
              <span className={'badge ' + (factor > 1 ? 'accent' : 'warn')}>{factor > 1 ? `≈ ${factor.toFixed(factor < 10 ? 1 : 0).replace('.', ',')}× langsamer` : 'nicht langsamer'}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
