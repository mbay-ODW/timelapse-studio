import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useEvent } from '../lib/events'
import { checkJobTransitions } from '../lib/jobNotify'
import type { JobsSnapshot } from '../lib/types'
import { JobCard } from './JobCard'

/** Kompaktes Job-Menü in der Kopfleiste mit Anzahl aktiver Jobs (R-2). */
export function JobsDropdown() {
  const snap = useEvent<JobsSnapshot>('jobs')
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (snap) checkJobTransitions(snap.jobs) }, [snap])
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  const active = snap?.jobs.filter((j) => ['queued', 'preparing', 'rendering'].includes(j.status)) ?? []
  const recent = snap?.jobs.filter((j) => !['queued', 'preparing', 'rendering'].includes(j.status)).slice(0, 3) ?? []
  const running = active.find((j) => j.status === 'rendering')
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className={'jobs-btn' + (active.length ? ' busy' : '')} onClick={() => setOpen(!open)}>
        ⚙<span className="jobs-label"> Jobs</span>{active.length > 0 && <span className="count">{active.length}</span>}
        {running && <span className="mini-progress"><span style={{ width: `${running.percent}%` }} /></span>}
      </button>
      {open && (
        <div className="popover jobs-pop">
          {active.length === 0 && <div className="muted small" style={{ padding: 8 }}>Keine aktiven Jobs.</div>}
          {active.map((j) => <JobCard key={j.id} job={j} compact />)}
          {recent.length > 0 && <div className="muted small" style={{ padding: '6px 4px 0' }}>Zuletzt</div>}
          {recent.map((j) => <JobCard key={j.id} job={j} compact />)}
          {snap?.render_window && !snap.window_open && <div className="badge warn">Render-Fenster {snap.render_window} – große Jobs warten</div>}
          <Link to="/jobs" className="btn" style={{ justifyContent: 'center' }} onClick={() => setOpen(false)}>Alle Jobs</Link>
        </div>
      )}
    </div>
  )
}
