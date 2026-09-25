import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useEvent } from '../lib/events'
import { fmtBytes } from '../lib/format'
import { requestNotifyPermission } from '../lib/jobNotify'
import type { Job, JobsSnapshot } from '../lib/types'
import { JobCard } from '../components/JobCard'

export function JobsPage() {
  const snap = useEvent<JobsSnapshot>('jobs')
  const [all, setAll] = useState<Job[]>([])
  const [storage, setStorage] = useState<{ renders_bytes: number; free_bytes: number } | null>(null)
  const load = () => { api.get<Job[]>('/api/jobs').then(setAll).catch(() => {}); api.get<typeof storage>('/api/storage').then(setStorage).catch(() => {}) }
  useEffect(() => { load(); requestNotifyPermission() }, [])
  // Live-Stand aus SSE einmischen
  const live = new Map((snap?.jobs ?? []).map((j) => [j.id, j]))
  const jobs = all.map((j) => live.get(j.id) ?? j)
  for (const j of snap?.jobs ?? []) if (!all.some((a) => a.id === j.id)) jobs.unshift(j)
  const active = jobs.filter((j) => ['preparing', 'rendering'].includes(j.status))
  const queued = jobs.filter((j) => j.status === 'queued')
  const done = jobs.filter((j) => !['queued', 'preparing', 'rendering'].includes(j.status))
  useEffect(() => { load() }, [snap?.active])

  return (
    <div className="page stack">
      <div className="row wrap">
        <h1 className="grow">Render-Jobs</h1>
        {storage && <span className="muted small">Renders {fmtBytes(storage.renders_bytes)} · frei {fmtBytes(storage.free_bytes)}</span>}
      </div>
      {snap?.render_window && <div className={'badge ' + (snap.window_open ? 'ok' : 'warn')}>Render-Fenster {snap.render_window}: {snap.window_open ? 'offen' : 'geschlossen – finale Renders warten'}</div>}
      <h2>Aktiv</h2>
      {active.length ? active.map((j) => <JobCard key={j.id} job={j} onChanged={load} />) : <div className="muted small">Nichts in Arbeit.</div>}
      {queued.length > 0 && <><h2>Warteschlange</h2>{queued.map((j) => <JobCard key={j.id} job={j} onChanged={load} queueControls />)}</>}
      <h2>Verlauf</h2>
      {done.length ? done.map((j) => <JobCard key={j.id} job={j} onChanged={load} />) : <div className="muted small">Noch keine abgeschlossenen Jobs.</div>}
    </div>
  )
}
