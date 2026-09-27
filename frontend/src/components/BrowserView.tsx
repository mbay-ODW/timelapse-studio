import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { dayToMs, fmtDate, fmtDateTime, fmtNum, msToDay } from '../lib/format'
import { useLocal } from '../lib/useLocal'
import { Histogram, type HistItem } from './Histogram'
import { Lightbox } from './Lightbox'
import { Scrubber } from './Scrubber'
import { TILE_SIZES, TimelineGrid, type Bucket, type DaySel, type GridHandle } from './TimelineGrid'
import { toastError } from './Toast'

export type ProjectCtx = {
  id: number
  evalKey: string                       // ändert sich bei jeder neuen Auswertung
  distribution: [number, number][]      // [Tag-ms, Anzahl]
  count: number
  onRange: (from: string, to: string, mode: 'include' | 'exclude') => void
  onMarks: (ids: number[], mode: 'include' | 'exclude' | 'clear') => Promise<void>
}

/** Immich-ähnlicher Browser: Histogramm + virtualisiertes Grid + Scrubber + Lightbox (§5). */
export function BrowserView({ sources, project }: { sources?: number[]; project?: ProjectCtx }) {
  const sourcesParam = sources?.length ? sources.join(',') : ''
  const [buckets, setBuckets] = useState<Bucket[]>([])
  const [zoom, setZoom] = useLocal('zoom', 1)
  const [histMode, setHistMode] = useLocal<'day' | 'hour'>('histMode', 'day')
  const [hourItems, setHourItems] = useState<HistItem[]>([])
  const [onlySelected, setOnlySelected] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [currentDay, setCurrentDay] = useState<string>()
  const [pendingRange, setPendingRange] = useState<{ from: string; to: string; label: string } | null>(null)
  const [lightbox, setLightbox] = useState<{ ids: number[]; times: number[]; index: number } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const grid = useRef<GridHandle>(null)

  useEffect(() => {
    api.get<Bucket[]>(`/api/timeline/buckets${sourcesParam ? `?sources=${sourcesParam}` : ''}`).then(setBuckets).catch(toastError)
  }, [sourcesParam])
  useEffect(() => {
    if (histMode !== 'hour') return
    api.get<{ items: HistItem[] }>(`/api/stats/histogram?bucket=hour${sourcesParam ? `&sources=${sourcesParam}` : ''}`)
      .then((r) => setHourItems(r.items)).catch(toastError)
  }, [histMode, sourcesParam])

  // --- Auswahl pro Tag (B-7); Schlüssel enthält die Auswertung → neue Regeln = neuer Cache-Eintrag
  const selCache = useRef(new Map<string, DaySel>())
  const selPending = useRef(new Set<string>())
  const [selVersion, setSelVersion] = useState(0)
  const evalKey = project?.evalKey ?? ''
  const requestSelection = useCallback((day: string) => {
    if (!project) return
    const key = `${project.evalKey}|${day}`
    if (selCache.current.has(key) || selPending.current.has(key)) return
    selPending.current.add(key)
    const from = dayToMs(day)
    api.get<{ ids: number[]; include: number[]; exclude: number[] }>(`/api/projects/${project.id}/selection?from=${from}&to=${from + 86_400_000}`)
      .then((r) => {
        if (selCache.current.size > 400) selCache.current.clear()
        selCache.current.set(key, { ids: new Set(r.ids), include: new Set(r.include), exclude: new Set(r.exclude) })
        setSelVersion((v) => v + 1)
      })
      .catch(() => {})
      .finally(() => selPending.current.delete(key))
  }, [project])
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const selectionFor = useCallback((day: string) => selCache.current.get(`${evalKey}|${day}`), [selVersion, evalKey])

  const selectedByDay = useMemo(() => new Map(project?.distribution ?? []), [project?.distribution])
  const gridBuckets = useMemo(() => {
    if (!project || !onlySelected) return buckets
    return project.distribution.map(([ms, n]) => ({ day: msToDay(ms), count: n }))
  }, [buckets, project, onlySelected])

  const dayHist: HistItem[] = useMemo(() => buckets.map((b) => [dayToMs(b.day), b.count]), [buckets])

  const openLightbox = (id: number) => {
    const items = grid.current?.orderedItems() ?? []
    const ids = items.map((i) => i[0])
    const index = ids.indexOf(id)
    if (index >= 0) setLightbox({ ids, times: items.map((i) => i[1]), index })
  }

  const applyMarks = async (mode: 'include' | 'exclude' | 'clear', ids = [...selected]) => {
    if (!project || !ids.length) return
    try {
      await project.onMarks(ids, mode)
      if (ids.length === selected.size) setSelected(new Set())
    } catch (e) { toastError(e) }
  }

  const total = buckets.reduce((a, b) => a + b.count, 0)

  return (
    <div className="browser">
      <div className="browser-toolbar row wrap">
        <div className="seg">
          <button className={histMode === 'day' ? 'active' : ''} onClick={() => setHistMode('day')}>Tage</button>
          <button className={histMode === 'hour' ? 'active' : ''} onClick={() => setHistMode('hour')}>Stunden</button>
        </div>
        <span className="muted small">{fmtNum(total)} Bilder · {buckets.length} Tage
          {project && <> · <b style={{ color: 'var(--accent)' }}>{fmtNum(project.count)} ausgewählt</b></>}</span>
        <span className="muted small hide-mobile">· im Histogramm ziehen: {project ? 'Zeitraum ausschließen/behalten' : 'hinspringen'}</span>
        <div className="spacer" />
        {project && (
          <label className="row small"><input type="checkbox" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />nur Auswahl</label>
        )}
        {project && (
          <button className={selectMode ? 'active' : ''} onClick={() => { setSelectMode(!selectMode); if (selectMode) setSelected(new Set()) }}
            title="Mehrfachauswahl: Klick, Shift-Klick oder Rechteck ziehen">☐ Auswählen</button>
        )}
        <div className="seg" title="Kachelgröße">
          {TILE_SIZES.map((_, i) => (
            <button key={i} className={zoom === i ? 'active' : ''} onClick={() => setZoom(i)}>{['S', 'M', 'L', 'XL'][i]}</button>
          ))}
        </div>
      </div>
      <div className="browser-hist">
        {histMode === 'day'
          ? <Histogram items={dayHist} sizeMs={86_400_000} selected={project ? selectedByDay : undefined}
              onRange={(a, b) => { if (project) setPendingRange({ from: msToDay(a), to: msToDay(b - 86_400_000), label: `${fmtDate(a)} – ${fmtDate(b - 86_400_000)}` }); else grid.current?.scrollToDay(msToDay(a)) }} />
          : <Histogram items={hourItems} sizeMs={3_600_000}
              onRange={(a, b) => { if (project) setPendingRange({ from: new Date(a).toISOString().slice(0, 16), to: new Date(b).toISOString().slice(0, 16), label: `${fmtDateTime(a).slice(0, 16)} – ${fmtDateTime(b).slice(0, 16)}` }); else grid.current?.scrollToDay(msToDay(a)) }} />}
      </div>
      {pendingRange && project && (
        <div className="range-choice">
          <span>Zeitraum <b>{pendingRange.label}</b>:</span>
          <button className="primary" onClick={() => { project.onRange(pendingRange.from, pendingRange.to, 'exclude'); setPendingRange(null) }}>Ausschließen</button>
          <button onClick={() => { project.onRange(pendingRange.from, pendingRange.to, 'include'); setPendingRange(null) }}>Nur diesen behalten</button>
          <button className="ghost" onClick={() => { grid.current?.scrollToDay(pendingRange.from.slice(0, 10)); setPendingRange(null) }}>Nur hinspringen</button>
          <button className="ghost icon" onClick={() => setPendingRange(null)}>✕</button>
        </div>
      )}
      <div className="browser-body">
        <div ref={scrollRef} className="browser-scroll">
          {buckets.length === 0
            ? <div className="empty">Noch keine Bilder indexiert.</div>
            : <TimelineGrid ref={grid} buckets={gridBuckets} sourcesParam={sourcesParam} zoom={zoom}
                selectionFor={project ? selectionFor : undefined} requestSelection={project ? requestSelection : undefined}
                onlySelected={onlySelected} selectMode={selectMode} selected={selected} onSelectedChange={setSelected}
                onOpen={openLightbox} onVisibleDayChange={setCurrentDay} scrollRef={scrollRef} />}
        </div>
        <Scrubber buckets={gridBuckets} currentDay={currentDay} onJump={(d) => grid.current?.scrollToDay(d)} />
      </div>
      {selected.size > 0 && project && (
        <div className="action-bar">
          <b>{fmtNum(selected.size)} markiert</b>
          <button onClick={() => applyMarks('exclude')}>Ausschließen</button>
          <button onClick={() => applyMarks('include')}>Einschließen</button>
          <button onClick={() => applyMarks('clear')}>Markierung entfernen</button>
          <button className="ghost" onClick={() => setSelected(new Set())}>Aufheben</button>
        </div>
      )}
      {lightbox && (
        <Lightbox ids={lightbox.ids} index={lightbox.index} onIndex={(i) => setLightbox({ ...lightbox, index: i })}
          onClose={() => setLightbox(null)}
          actions={project ? (id) => {
            const day = selectionFor(msToDay(lightbox.times[lightbox.ids.indexOf(id)]))
            const excluded = day ? day.exclude.has(id) : false
            return excluded
              ? <button onClick={() => applyMarks('clear', [id])}>Wieder zulassen</button>
              : <button onClick={() => applyMarks('exclude', [id])}>Ausschließen</button>
          } : undefined} />
      )}
    </div>
  )
}
