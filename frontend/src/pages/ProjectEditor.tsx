import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { BrowserView, type ProjectCtx } from '../components/BrowserView'
import { CropEditor } from '../components/CropEditor'
import { JobCard } from '../components/JobCard'
import { PreviewPlayer } from '../components/PreviewPlayer'
import { RulesPanel } from '../components/RulesPanel'
import { toast, toastError } from '../components/Toast'
import { VideoPanel } from '../components/VideoPanel'
import { api } from '../lib/api'
import { useEvent } from '../lib/events'
import { requestNotifyPermission } from '../lib/jobNotify'
import { useLocal } from '../lib/useLocal'
import type { Evaluation, Job, JobsSnapshot, Project, Rule, Source, VideoParams } from '../lib/types'

type Tab = 'images' | 'video' | 'renders'

export function ProjectEditor() {
  const { id } = useParams()
  const pid = Number(id)
  const nav = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [rules, setRules] = useState<Rule[]>([])
  const [params, setParams] = useState<VideoParams | null>(null)
  const [ev, setEv] = useState<Evaluation | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [tab, setTab] = useLocal<Tab>('projectTab', 'images')
  const [crop, setCrop] = useState(false)
  const [saving, setSaving] = useState(false)
  const evalSeq = useRef(0)

  const evaluate = useCallback(async () => {
    const seq = ++evalSeq.current
    try {
      const r = await api.post<Evaluation>(`/api/projects/${pid}/evaluate`)
      if (seq === evalSeq.current) setEv(r)
    } catch (e) { toastError(e) }
  }, [pid])

  useEffect(() => {
    api.get<Project>(`/api/projects/${pid}`).then((p) => { setProject(p); setRules(p.rules ?? []); setParams(p.params) })
      .catch((e) => { toastError(e); nav('/projects') })
    api.get<Source[]>('/api/sources').then(setSources).catch(() => {})
    evaluate()
  }, [pid, nav, evaluate])

  // Autosave (J-3): Regeln und Parameter getrennt entprellt speichern, danach neu auswerten
  const ruleTimer = useRef<number>(0)
  const saveRules = (next: Rule[]) => {
    setRules(next)
    setSaving(true)
    window.clearTimeout(ruleTimer.current)
    ruleTimer.current = window.setTimeout(async () => {
      try {
        const saved = await api.put<Rule[]>(`/api/projects/${pid}/rules`, next)
        setRules(saved)
        await evaluate()
      } catch (e) { toastError(e) } finally { setSaving(false) }
    }, 350)
  }
  const paramTimer = useRef<number>(0)
  const pendingParams = useRef<Partial<VideoParams>>({})
  const changeParams = (patch: Partial<VideoParams>) => {
    setParams((p) => (p ? { ...p, ...patch } : p))
    pendingParams.current = { ...pendingParams.current, ...patch }
    setSaving(true)
    window.clearTimeout(paramTimer.current)
    paramTimer.current = window.setTimeout(async () => {
      const body = pendingParams.current
      pendingParams.current = {}
      try {
        const p = await api.patch<Project>(`/api/projects/${pid}`, { params: body })
        setProject(p)
        await evaluate()
      } catch (e) { toastError(e) } finally { setSaving(false) }
    }, 400)
  }
  const rename = async (name: string) => {
    if (!project || name === project.name || !name.trim()) return
    try { setProject(await api.patch<Project>(`/api/projects/${pid}`, { name })) } catch (e) { toastError(e) }
  }

  const setDateRange = (from: string, to: string, mode: 'include' | 'exclude') => {
    const range = { from, to }
    const same = (r: Rule) => r.type === 'date_range' && (r.params.mode ?? 'include') === mode
    const i = rules.findIndex(same)
    let next: Rule[]
    if (i < 0) next = [...rules, { type: 'date_range', enabled: true, params: { mode, ranges: [range] } }]
    else if (mode === 'exclude') {
      // weitere Lücke an die vorhandene Ausschluss-Regel anhängen
      const r = rules[i]
      const ranges = (r.params.ranges ?? [{ from: r.params.from ?? '', to: r.params.to ?? '' }]).filter((x: typeof range) => x.from || x.to)
      next = rules.map((x, j) => (j === i ? { ...x, enabled: true, params: { mode, ranges: [...ranges, range] } } : x))
    } else next = rules.map((x, j) => (j === i ? { ...x, enabled: true, params: { mode, ranges: [range] } } : x))
    saveRules(next)
    toast(`${mode === 'exclude' ? 'Ausgeschlossen' : 'Nur noch'}: ${from.replace('T', ' ')} – ${to.replace('T', ' ')}`)
  }
  const setMarks = async (ids: number[], mode: 'include' | 'exclude' | 'clear') => {
    await api.post(`/api/projects/${pid}/marks`, { ids, mode })
    // manuelle Regel sichtbar machen, falls noch nicht vorhanden
    if (mode !== 'clear' && !rules.some((r) => r.type === 'manual')) saveRules([...rules, { type: 'manual', enabled: true, params: {} }])
    else await evaluate()
    toast(mode === 'exclude' ? `${ids.length} ausgeschlossen` : mode === 'include' ? `${ids.length} eingeschlossen` : 'Markierung entfernt')
  }

  const render = async (kind: 'render' | 'preview', range?: { start?: number; end?: number; seconds?: number }) => {
    try {
      requestNotifyPermission()
      await api.post<Job>('/api/jobs', { project_id: pid, kind, ...(range ?? {}) })
      toast(kind === 'render' ? 'Render-Job eingereiht' : 'Schnell-Preview eingereiht')
      if (kind === 'preview' || tab !== 'video') setTab('renders')
    } catch (e) { toastError(e) }
  }

  const ctx: ProjectCtx | undefined = useMemo(() => ev ? {
    id: pid, evalKey: ev.key, distribution: ev.distribution, count: ev.count, onRange: setDateRange, onMarks: setMarks,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  } : undefined, [ev, pid, rules])

  const sourceIds = useMemo(() => {
    const r = rules.find((x) => x.type === 'sources' && x.enabled)
    return (r?.params.source_ids as number[] | undefined) ?? []
  }, [rules])

  if (!project || !params) return <div className="empty">lädt…</div>
  return (
    <div className="editor">
      <aside className="editor-side">
        <div className="row" style={{ padding: '10px 12px 0' }}>
          <input className="name-input grow" defaultValue={project.name} key={project.name}
            onBlur={(e) => rename(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
          <span className="muted small" title="Autosave">{saving ? 'speichert…' : '✓ gespeichert'}</span>
        </div>
        <RulesPanel rules={rules} onChange={saveRules} evaluation={ev} sources={sources}
          onClearMarks={async () => { await api.del(`/api/projects/${pid}/marks`); await evaluate() }} />
      </aside>
      <section className="editor-main">
        <div className="editor-tabs">
          <button className={tab === 'images' ? 'on' : ''} onClick={() => setTab('images')}>Bilder</button>
          <button className={tab === 'video' ? 'on' : ''} onClick={() => setTab('video')}>Video & Vorschau</button>
          <button className={tab === 'renders' ? 'on' : ''} onClick={() => setTab('renders')}>Renders</button>
        </div>
        <div className={'editor-content' + (tab === 'images' ? ' fill' : '')}>
          {tab === 'images' && <BrowserView sources={sourceIds} project={ctx} />}
          {tab === 'video' && (
            <div className="video-tab">
              {ev && <PreviewPlayer projectId={pid} evalKey={ev.key} params={params} total={ev.count} />}
              <VideoPanel params={params} onChange={changeParams} evaluation={ev} rules={rules} onRules={saveRules}
                onOpenCrop={() => setCrop(true)} onRender={render} />
            </div>
          )}
          {tab === 'renders' && <ProjectJobs pid={pid} />}
        </div>
      </section>
      {crop && <CropEditor projectId={pid} initial={params.crop} onClose={() => setCrop(false)}
        onSave={(r) => { changeParams({ crop: r }); setCrop(false) }} />}
    </div>
  )
}

function ProjectJobs({ pid }: { pid: number }) {
  const snap = useEvent<JobsSnapshot>('jobs')
  const [jobs, setJobs] = useState<Job[]>([])
  const load = useCallback(() => api.get<Job[]>(`/api/jobs?project_id=${pid}`).then(setJobs).catch(() => {}), [pid])
  useEffect(() => { load() }, [load, snap?.active])
  const live = new Map((snap?.jobs ?? []).map((j) => [j.id, j]))
  const merged = jobs.map((j) => live.get(j.id) ?? j)
  return (
    <div className="page stack">
      {merged.length === 0 && <div className="card empty">Noch keine Renders für dieses Projekt.</div>}
      {merged.map((j) => <JobCard key={j.id} job={j} onChanged={load} />)}
    </div>
  )
}
