import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { fmtBytes, fmtDuration, fmtNum } from '../lib/format'
import type { Job } from '../lib/types'
import { toast, toastError } from './Toast'

export const STATUS: Record<Job['status'], [string, string]> = {
  queued: ['wartend', ''], preparing: ['vorbereitend', 'accent'], rendering: ['rendernd', 'accent'],
  done: ['fertig', 'ok'], failed: ['fehlgeschlagen', 'err'], cancelled: ['abgebrochen', 'warn'],
  interrupted: ['abgebrochen – neu starten?', 'warn'],
}

export function JobCard({ job, compact, onChanged, queueControls }: {
  job: Job; compact?: boolean; onChanged?: () => void; queueControls?: boolean
}) {
  const [showLog, setShowLog] = useState(false)
  const [log, setLog] = useState<string | null>(null)
  const [showVideo, setShowVideo] = useState(false)
  const [label, cls] = STATUS[job.status]
  const active = job.status === 'preparing' || job.status === 'rendering'
  const act = (fn: () => Promise<unknown>, msg?: string) => async () => {
    try { await fn(); if (msg) toast(msg); onChanged?.() } catch (e) { toastError(e) }
  }
  const cancel = act(async () => { if (!confirm('Job wirklich abbrechen?')) throw new Error('Abgebrochen'); await api.post(`/api/jobs/${job.id}/cancel`) }, 'Abbruch angefordert')
  const loadLog = async () => { setShowLog(!showLog); if (!log) setLog(await fetch(`/api/jobs/${job.id}/log`).then((r) => r.text())) }

  return (
    <div className={'job-card' + (compact ? ' compact' : '')}>
      <div className="row wrap">
        <span className={'badge ' + cls}>{label}{job.cancel_requested && active ? ' · bricht ab…' : ''}</span>
        {job.kind === 'preview' && <span className="badge">Schnell-Preview</span>}
        <b className="grow" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {job.project_id ? <Link to={`/projects/${job.project_id}`}>{job.project_name}</Link> : job.project_name}
        </b>
        {!compact && <span className="muted small">#{job.id}</span>}
      </div>
      {!compact && <div className="muted small">{job.summary}{job.range ? ` · Frames ${job.range.start}–${job.range.end ?? 'Ende'}` : ''}</div>}
      {(active || job.status === 'queued') && (
        <>
          <div className={'progress' + (job.status === 'preparing' ? ' indeterminate' : '')}><div style={{ width: `${job.percent}%` }} /></div>
          <div className="row wrap small job-stats">
            <span><b>{job.percent.toFixed(1)} %</b></span>
            {job.phase && <span>{job.phase}</span>}
            <span>{fmtNum(job.frames_done)} / {fmtNum(job.frames_total)} Frames</span>
            {job.elapsed_s != null && <span>Dauer {fmtDuration(job.elapsed_s)}</span>}
            {job.eta_s != null && <span>Rest {fmtDuration(job.eta_s)}</span>}
            {job.fps_current != null && <span>{job.fps_current.toFixed(1)} fps</span>}
            {job.speed != null && <span>{job.speed.toFixed(2)}×</span>}
            {job.status === 'queued' && job.estimate && <span className="muted">geschätzt {fmtDuration(job.estimate.render_s)}</span>}
          </div>
        </>
      )}
      {job.status === 'done' && (
        <div className="row wrap small job-stats">
          <span>Dauer {fmtDuration(job.elapsed_s)}</span>
          <span>{fmtBytes(job.output_size)}</span>
          {job.out_w && <span>{job.out_w}×{job.out_h}</span>}
          <span className="mono">{job.output_name}</span>
        </div>
      )}
      {(job.status === 'failed' || job.status === 'interrupted' || job.status === 'cancelled') && job.error && (
        <div className={job.status === 'failed' ? 'error-box small' : 'muted small'}>{job.error}</div>
      )}
      {!compact && (
        <div className="row wrap">
          {job.status === 'queued' && queueControls && <>
            <button className="small" onClick={act(() => api.post(`/api/jobs/${job.id}/move`, { direction: 'top' }))} title="an den Anfang">⤒</button>
            <button className="small" onClick={act(() => api.post(`/api/jobs/${job.id}/move`, { direction: 'up' }))}>↑</button>
            <button className="small" onClick={act(() => api.post(`/api/jobs/${job.id}/move`, { direction: 'down' }))}>↓</button>
          </>}
          {(active || job.status === 'queued') && <button className="small danger" onClick={cancel} disabled={job.cancel_requested}>Abbrechen</button>}
          {job.output_exists && <>
            <button className="small" onClick={() => setShowVideo(!showVideo)}>{showVideo ? 'Player schließen' : '▶ Abspielen'}</button>
            <a className="btn small" href={`/api/jobs/${job.id}/download`}>Download</a>
          </>}
          {!active && job.status !== 'queued' && job.project_id && (
            <button className="small" onClick={act(() => api.post(`/api/jobs/${job.id}/rerun`), 'Neu eingereiht')}>
              {job.status === 'interrupted' ? 'Neu starten' : 'Mit gleichen Parametern neu rendern'}</button>
          )}
          {job.status !== 'queued' && <button className="small ghost" onClick={loadLog}>{showLog ? 'Log ausblenden' : 'Log'}</button>}
          <div className="spacer" />
          {!active && job.status !== 'queued' && (
            <button className="small ghost danger" onClick={act(async () => { if (!confirm('Job und Video löschen?')) throw new Error('Abgebrochen'); await api.del(`/api/jobs/${job.id}`) })}>Löschen</button>
          )}
        </div>
      )}
      {showVideo && job.output_exists && <video className="job-video" src={`/api/jobs/${job.id}/video`} controls autoPlay playsInline />}
      {showLog && (
        <div className="stack" style={{ gap: 4 }}>
          <pre className="log">{log ?? 'lädt…'}</pre>
          <a className="small" href={`/api/jobs/${job.id}/log?full=true`}>vollständiges Log herunterladen</a>
        </div>
      )}
    </div>
  )
}
