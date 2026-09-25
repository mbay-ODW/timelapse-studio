import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Project } from '../lib/types'
import { toast, toastError } from '../components/Toast'

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const load = () => api.get<Project[]>('/api/projects').then(setProjects).catch(toastError)
  useEffect(() => { load() }, [])

  const create = async () => {
    const name = prompt('Name des Projekts', 'Neues Projekt')
    if (name == null) return
    try { const p = await api.post<Project>('/api/projects', { name }); nav(`/projects/${p.id}`) } catch (e) { toastError(e) }
  }
  const importFile = async (f: File) => {
    try {
      const data = JSON.parse(await f.text())
      const p = await api.post<Project>('/api/projects/import', data)
      toast('Projekt importiert')
      nav(`/projects/${p.id}`)
    } catch (e) { toastError(e) }
  }
  const remove = async (p: Project) => {
    if (!confirm(`Projekt „${p.name}“ löschen? Quellbilder bleiben unberührt.`)) return
    const renders = (p.renders ?? 0) > 0 && confirm('Zugehörige Render-Videos ebenfalls löschen?')
    try { await api.del(`/api/projects/${p.id}?delete_renders=${renders}`); load() } catch (e) { toastError(e) }
  }

  return (
    <div className="page stack">
      <div className="row wrap">
        <h1 className="grow">Projekte</h1>
        <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
        <button onClick={() => fileRef.current?.click()}>Importieren</button>
        <button className="primary" onClick={create}>+ Neues Projekt</button>
      </div>
      {projects && projects.length === 0 && (
        <div className="card empty">Noch keine Projekte. Lege eines an, um eine Auswahl und ein Video zu erstellen.</div>
      )}
      <div className="project-grid">
        {projects?.map((p) => (
          <div key={p.id} className="card project-card">
            <Link to={`/projects/${p.id}`} className="project-name">{p.name}</Link>
            <div className="muted small">
              {p.params.resolution === 'source' ? 'Original' : p.params.resolution + 'p'} · {p.params.fps} fps · {p.params.codec.toUpperCase()}
              {' · '}{p.renders ?? 0} Renders
            </div>
            <div className="muted small">geändert {new Date(p.updated_at * 1000).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })}</div>
            <div className="row" style={{ marginTop: 8 }}>
              <Link to={`/projects/${p.id}`} className="btn">Öffnen</Link>
              <button onClick={async () => { try { const d = await api.post<Project>(`/api/projects/${p.id}/duplicate`); toast('Dupliziert'); nav(`/projects/${d.id}`) } catch (e) { toastError(e) } }}>Duplizieren</button>
              <a className="btn" href={`/api/projects/${p.id}/export`}>Export</a>
              <div className="spacer" />
              <button className="danger ghost" onClick={() => remove(p)}>Löschen</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
