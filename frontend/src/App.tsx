import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { JobsDropdown } from './components/JobsDropdown'
import { ThemeToggle } from './components/ThemeToggle'
import { Toasts } from './components/Toast'
import { api } from './lib/api'
import { useEvent } from './lib/events'
import type { ScanStatus } from './lib/types'
import { JobsPage } from './pages/JobsPage'
import { LibraryPage } from './pages/LibraryPage'
import { ProjectEditor } from './pages/ProjectEditor'
import { ProjectsPage } from './pages/ProjectsPage'
import { SourcesPage } from './pages/SourcesPage'
import { UploadPage } from './pages/UploadPage'

function IndexBadge() {
  const s = useEvent<ScanStatus>('scan')
  const scanning = s?.scans.some((x) => x.status === 'scanning')
  if (!s || (!scanning && !s.thumbs.pending)) return null
  const pct = s.thumbs.total ? Math.floor((100 * s.thumbs.done) / s.thumbs.total) : 0
  return <NavLink to="/sources" className="badge accent small" title="Indexierung läuft">{scanning ? 'Scan…' : `Index ${pct} %`}</NavLink>
}

export default function App() {
  const [user, setUser] = useState<string | null>(null)
  useEffect(() => { api.get<{ remote_user: string | null }>('/api/me').then((r) => setUser(r.remote_user)).catch(() => {}) }, [])
  return (
    <div className="app">
      <header className="header">
        <NavLink to="/" className="brand"><img src="/favicon.svg" alt="" /><span>Timelapse Studio</span></NavLink>
        <nav className="nav">
          <NavLink to="/projects">Projekte</NavLink>
          <NavLink to="/library">Bibliothek</NavLink>
          <NavLink to="/upload">Upload</NavLink>
          <NavLink to="/sources">Quellen</NavLink>
        </nav>
        <IndexBadge />
        <div className="spacer" />
        <JobsDropdown />
        {user && <span className="muted small hide-mobile" title="angemeldet über Authelia">{user}</span>}
        <ThemeToggle />
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectEditor />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="*" element={<div className="empty">Seite nicht gefunden</div>} />
        </Routes>
      </main>
      <Toasts />
    </div>
  )
}
