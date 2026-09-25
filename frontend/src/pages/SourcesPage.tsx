import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useEvent } from '../lib/events'
import { fmtDate, fmtDuration, fmtNum } from '../lib/format'
import type { ScanStatus, Source } from '../lib/types'
import { toast, toastError } from '../components/Toast'

const TS_LABEL: Record<string, string> = { exif: 'EXIF', filename: 'Dateiname', mtime: 'Änderungsdatum' }

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([])
  const [edit, setEdit] = useState<Source | null>(null)
  const status = useEvent<ScanStatus>('scan')
  const load = useCallback(() => api.get<Source[]>('/api/sources').then(setSources).catch(toastError), [])
  useEffect(() => { load() }, [load])
  // Nach Scan-Ende Zahlen neu laden
  const doneKey = status?.scans.map((s) => s.status + s.finished_at).join()
  useEffect(() => { load() }, [doneKey, load])

  const th = status?.thumbs
  const pct = th && th.total ? (100 * (th.done + th.errors)) / th.total : 0

  return (
    <div className="page stack">
      <div className="row"><h1 className="grow">Quellen</h1></div>
      {th && (
        <div className="card stack">
          <div className="row wrap">
            <h2 className="grow" style={{ margin: 0 }}>Indexierung</h2>
            <span className="muted small">
              {fmtNum(th.done)} / {fmtNum(th.total)} Vorschaubilder
              {th.errors > 0 && <> · <span style={{ color: 'var(--err)' }}>{fmtNum(th.errors)} Fehler</span></>}
              {th.pending > 0 && th.rate > 0 && <> · {th.rate.toLocaleString('de-DE')} /s · Rest {fmtDuration(th.eta_s)}</>}
            </span>
          </div>
          <div className={'progress' + (th.pending === 0 ? ' ok' : '')}><div style={{ width: `${pct}%` }} /></div>
        </div>
      )}
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        <table className="list">
          <thead>
            <tr><th>Quelle</th><th>Bilder</th><th>Zeitraum</th><th>Zeitstempel</th><th>Scan</th><th></th></tr>
          </thead>
          <tbody>
            {sources.map((s) => {
              const sc = status?.scans.find((x) => x.source_id === s.id)
              return (
                <tr key={s.id} style={{ opacity: s.enabled && s.present ? 1 : 0.55 }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{s.display_name}</div>
                    <div className="muted small mono">{s.kind === 'upload' ? 'Upload' : '/sources/' + s.name}
                      {!s.present && ' · fehlt'}</div>
                  </td>
                  <td>{fmtNum(s.image_count)}</td>
                  <td className="small">{s.first_ms ? `${fmtDate(s.first_ms)} – ${fmtDate(s.last_ms!)}` : '–'}</td>
                  <td className="small">{s.ts_order.map((t) => TS_LABEL[t]).join(' → ')}</td>
                  <td className="small"><ScanCell sc={sc} /></td>
                  <td>
                    <div className="row">
                      <label className="row small"><input type="checkbox" checked={s.enabled}
                        onChange={(e) => api.patch(`/api/sources/${s.id}`, { enabled: e.target.checked }).then(load).catch(toastError)} />aktiv</label>
                      <button disabled={!s.present || sc?.status === 'scanning' || sc?.status === 'queued'}
                        onClick={() => api.post(`/api/sources/${s.id}/scan`).then(() => toast('Scan eingereiht')).catch(toastError)}>Scannen</button>
                      <button onClick={() => setEdit(s)}>Einstellungen</button>
                    </div>
                  </td>
                </tr>
              )
            })}
            {sources.length === 0 && <tr><td colSpan={6} className="empty">Keine Quellen gefunden. Ordner unter /sources mounten.</td></tr>}
          </tbody>
        </table>
      </div>
      {edit && <SourceDialog source={edit} onClose={() => { setEdit(null); load() }} />}
    </div>
  )
}

function ScanCell({ sc }: { sc?: ScanStatus['scans'][number] }) {
  if (!sc) return <span className="muted">–</span>
  if (sc.status === 'scanning') return <span className="badge accent">läuft · {fmtNum(sc.found)} gefunden</span>
  if (sc.status === 'queued') return <span className="badge">wartet</span>
  if (sc.status === 'error') return <span className="badge err" title={sc.message ?? ''}>Fehler</span>
  return (
    <span className="muted">
      {sc.finished_at ? new Date(sc.finished_at * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : ''}
      {' '}· +{fmtNum(sc.new)} / ~{fmtNum(sc.changed)} / −{fmtNum(sc.removed)}
    </span>
  )
}

type TestResult = { valid: boolean; error: string | null; samples: { file: string; parsed: string | null }[] }

function SourceDialog({ source, onClose }: { source: Source; onClose: () => void }) {
  const [name, setName] = useState(source.display_name)
  const [order, setOrder] = useState<string[]>(source.ts_order)
  const [pattern, setPattern] = useState(source.filename_pattern)
  const [test, setTest] = useState<TestResult | null>(null)

  useEffect(() => {
    const t = setTimeout(() => {
      api.post<TestResult>(`/api/sources/${source.id}/pattern-test`, { pattern }).then(setTest).catch(toastError)
    }, 300)
    return () => clearTimeout(t)
  }, [pattern, source.id])

  const move = (i: number, d: number) => {
    const o = [...order]
    const j = i + d
    if (j < 0 || j >= o.length) return
    ;[o[i], o[j]] = [o[j], o[i]]
    setOrder(o)
  }
  const toggle = (m: string) => setOrder(order.includes(m) ? order.filter((x) => x !== m) : [...order, m])

  const save = async () => {
    try {
      await api.patch(`/api/sources/${source.id}`, { display_name: name, ts_order: order, filename_pattern: pattern })
      toast('Gespeichert – Zeitstempel werden neu berechnet')
      onClose()
    } catch (e) { toastError(e) }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal stack" style={{ maxWidth: 640 }}>
        <h2>Quelle: {source.name}</h2>
        <label className="field">Anzeigename<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <div className="field">
          <span className="small muted">Zeitstempel-Reihenfolge (erster Treffer gewinnt)</span>
          {['exif', 'filename', 'mtime'].map((m) => {
            const i = order.indexOf(m)
            return (
              <div key={m} className="row">
                <input type="checkbox" checked={i >= 0} onChange={() => toggle(m)} />
                <span className="grow">{i >= 0 ? `${i + 1}. ` : ''}{TS_LABEL[m]}</span>
                <button className="icon ghost" disabled={i <= 0} onClick={() => move(i, -1)}>↑</button>
                <button className="icon ghost" disabled={i < 0 || i >= order.length - 1} onClick={() => move(i, 1)}>↓</button>
              </div>
            )
          })}
        </div>
        <label className="field">Dateinamen-Muster (Regex mit Gruppen Y m d H M S f, oder strftime wie <span className="mono">%Y%m%d-%H%M%S*</span>; leer = Standard)
          <textarea className="mono" rows={3} value={pattern} onChange={(e) => setPattern(e.target.value)} />
        </label>
        {test && !test.valid && <div className="error-box small">{test.error}</div>}
        {test?.valid && (
          <div className="small stack" style={{ gap: 2 }}>
            <span className="muted">Live-Test an zufälligen Dateien:</span>
            {test.samples.map((s) => (
              <div key={s.file} className="row">
                <span className="mono grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.file}</span>
                {s.parsed ? <span className="badge ok">{s.parsed}</span> : <span className="badge err">kein Treffer</span>}
              </div>
            ))}
          </div>
        )}
        <div className="row"><div className="spacer" /><button onClick={onClose}>Abbrechen</button>
          <button className="primary" onClick={save}>Speichern</button></div>
      </div>
    </div>
  )
}
