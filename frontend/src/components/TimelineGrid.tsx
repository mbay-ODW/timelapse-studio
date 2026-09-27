import { useVirtualizer } from '@tanstack/react-virtual'
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { thumbs } from '../lib/batchLoader'
import { dayToMs, fmtDateLong, fmtNum, fmtTime } from '../lib/format'

/** [id, taken_ms, width, height, brightness, thumb_status] */
export type Item = [number, number, number | null, number | null, number | null, number]
export type Bucket = { day: string; count: number }
export type DaySel = { ids: Set<number>; include: Set<number>; exclude: Set<number> }

export const TILE_SIZES = [96, 140, 200, 300]
const GAP = 4
const HEADER_H = 44

type Row =
  | { kind: 'header'; day: string; count: number; top: number; h: number }
  | { kind: 'row'; day: string; index: number; top: number; h: number }

export type GridHandle = {
  scrollToDay: (day: string) => void
  orderedItems: () => Item[]
}

type Props = {
  buckets: Bucket[]
  sourcesParam: string
  zoom: number
  /** Projekt-Kontext: Auswahl-Markierung (B-7) */
  selectionFor?: (day: string) => DaySel | undefined
  requestSelection?: (day: string) => void
  onlySelected?: boolean
  selectMode: boolean
  selected: Set<number>
  onSelectedChange: (s: Set<number>) => void
  onOpen: (id: number) => void
  onVisibleDayChange?: (day: string) => void
  scrollRef: React.RefObject<HTMLDivElement | null>
}

const dayCache = new Map<string, Item[]>()
const dayPending = new Map<string, Promise<Item[]>>()

export function clearDayCache() { dayCache.clear(); dayPending.clear() }

function loadDay(day: string, sourcesParam: string): Promise<Item[]> {
  const key = day + '|' + sourcesParam
  const hit = dayCache.get(key)
  if (hit) return Promise.resolve(hit)
  let p = dayPending.get(key)
  if (!p) {
    p = api.get<{ items: Item[] }>(`/api/timeline/day/${day}${sourcesParam ? `?sources=${sourcesParam}` : ''}`)
      .then((r) => { dayCache.set(key, r.items); dayPending.delete(key); return r.items })
      .catch((e) => { dayPending.delete(key); throw e })
    dayPending.set(key, p)
  }
  return p
}

export const TimelineGrid = forwardRef<GridHandle, Props>(function TimelineGrid(props, ref) {
  const { buckets, sourcesParam, zoom, selectionFor, requestSelection, onlySelected, selectMode, selected,
    onSelectedChange, onOpen, onVisibleDayChange, scrollRef } = props
  const [width, setWidth] = useState(800)
  const [days, setDays] = useState<Record<string, Item[]>>({})
  const lastClicked = useRef<number | null>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth - 24))
    ro.observe(el)
    setWidth(el.clientWidth - 24)
    return () => ro.disconnect()
  }, [scrollRef])

  const baseTile = TILE_SIZES[zoom] ?? 140
  const cols = Math.max(1, Math.floor((width + GAP) / (baseTile + GAP)))
  const tileW = (width - GAP * (cols - 1)) / cols
  const tileH = Math.round(tileW * 9 / 16)

  // Items eines Tages, ggf. auf Auswahl gefiltert
  const itemsOf = useCallback((day: string): Item[] | undefined => {
    const items = days[day]
    if (!items || !onlySelected) return items
    const sel = selectionFor?.(day)
    return sel ? items.filter((it) => sel.ids.has(it[0])) : undefined
  }, [days, onlySelected, selectionFor])

  const effectiveBuckets = useMemo(() => {
    if (!onlySelected) return buckets
    return buckets.filter((b) => b.count > 0)
  }, [buckets, onlySelected])

  const rows = useMemo(() => {
    const out: Row[] = []
    let top = 0
    for (const b of effectiveBuckets) {
      out.push({ kind: 'header', day: b.day, count: b.count, top, h: HEADER_H })
      top += HEADER_H
      const n = Math.ceil(b.count / cols)
      for (let i = 0; i < n; i++) {
        out.push({ kind: 'row', day: b.day, index: i, top, h: tileH + GAP })
        top += tileH + GAP
      }
    }
    return out
  }, [effectiveBuckets, cols, tileH])

  const dayStartIndex = useMemo(() => {
    const m = new Map<string, number>()
    rows.forEach((r, i) => { if (r.kind === 'header') m.set(r.day, i) })
    return m
  }, [rows])

  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => rows[i].h,
    overscan: 4,
  })

  useImperativeHandle(ref, () => ({
    scrollToDay: (day: string) => {
      const i = dayStartIndex.get(day)
      if (i != null) virt.scrollToOffset(rows[i].top, { align: 'start' })
    },
    orderedItems: () => {
      const all: Item[] = []
      for (const b of effectiveBuckets) { const it = itemsOf(b.day); if (it) all.push(...it) }
      return all
    },
  }), [dayStartIndex, rows, virt, effectiveBuckets, itemsOf])

  const vItems = virt.getVirtualItems()
  const visibleDays = useMemo(() => {
    const s: string[] = []
    for (const v of vItems) { const d = rows[v.index]?.day; if (d && s[s.length - 1] !== d) s.push(d) }
    return s
  }, [vItems, rows])
  const visibleKey = visibleDays.join(',')

  // Tages-Daten + Auswahl nachladen
  useEffect(() => {
    let alive = true
    for (const d of visibleDays) {
      if (!days[d]) loadDay(d, sourcesParam).then((items) => { if (alive) setDays((x) => (x[d] ? x : { ...x, [d]: items })) }).catch(() => {})
      requestSelection?.(d)
    }
    if (visibleDays[0]) onVisibleDayChange?.(visibleDays[0])
    return () => { alive = false }
    // requestSelection wechselt mit jeder neuen Auswertung → sichtbare Tage neu markieren
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleKey, sourcesParam, requestSelection])

  useEffect(() => { setDays({}) }, [sourcesParam])

  // Sichtbare Thumbnails priorisieren, veraltete Anfragen verwerfen
  useEffect(() => {
    const keep = new Set<number>()
    for (const v of vItems) {
      const r = rows[v.index]
      if (r?.kind !== 'row') continue
      const items = itemsOf(r.day)
      if (!items) continue
      for (const it of items.slice(r.index * cols, r.index * cols + cols)) keep.add(it[0])
    }
    thumbs.cancelPending(keep)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleKey, vItems.length, cols])

  const toggle = useCallback((id: number, shift: boolean) => {
    const next = new Set(selected)
    if (shift && lastClicked.current != null) {
      const all: number[] = []
      for (const b of effectiveBuckets) { const it = itemsOf(b.day); if (it) for (const x of it) all.push(x[0]) }
      const a = all.indexOf(lastClicked.current), z = all.indexOf(id)
      if (a >= 0 && z >= 0) {
        const [lo, hi] = a < z ? [a, z] : [z, a]
        for (let i = lo; i <= hi; i++) next.add(all[i])
        onSelectedChange(next)
        lastClicked.current = id
        return
      }
    }
    if (next.has(id)) next.delete(id)
    else next.add(id)
    lastClicked.current = id
    onSelectedChange(next)
  }, [selected, onSelectedChange, effectiveBuckets, itemsOf])

  // Rechteck-Auswahl
  const [rect, setRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  const rectStart = useRef<{ x: number; y: number; base: Set<number>; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const inner = useRef<HTMLDivElement>(null)

  const onPointerDown = (e: React.PointerEvent) => {
    if (!selectMode || e.button !== 0) return
    rectStart.current = { x: e.clientX, y: e.clientY, base: new Set(selected), moved: false }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const st = rectStart.current
    if (!st) return
    if (!st.moved && Math.hypot(e.clientX - st.x, e.clientY - st.y) < 6) return
    st.moved = true
    const r = { x0: Math.min(st.x, e.clientX), y0: Math.min(st.y, e.clientY), x1: Math.max(st.x, e.clientX), y1: Math.max(st.y, e.clientY) }
    setRect(r)
    const next = new Set(st.base)
    inner.current?.querySelectorAll<HTMLElement>('[data-id]').forEach((el) => {
      const b = el.getBoundingClientRect()
      if (b.right >= r.x0 && b.left <= r.x1 && b.bottom >= r.y0 && b.top <= r.y1) next.add(Number(el.dataset.id))
    })
    onSelectedChange(next)
  }
  const onPointerUp = () => {
    if (rectStart.current?.moved) suppressClick.current = true
    rectStart.current = null
    setRect(null)
  }

  return (
    <div ref={inner} style={{ height: virt.getTotalSize(), position: 'relative', margin: '0 12px', userSelect: selectMode ? 'none' : undefined }}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
      {vItems.map((v) => {
        const r = rows[v.index]
        if (r.kind === 'header') {
          const sel = selectionFor?.(r.day)
          return (
            <div key={v.key} className="day-header" style={{ position: 'absolute', top: r.top, left: 0, right: 0, height: HEADER_H }}>
              <span className="day-title">{fmtDateLong(dayToMs(r.day))}</span>
              <span className="muted small">{fmtNum(r.count)} Bilder{sel && !onlySelected ? ` · ${fmtNum(sel.ids.size)} ausgewählt` : ''}</span>
            </div>
          )
        }
        const items = itemsOf(r.day)
        const slice = items ? items.slice(r.index * cols, r.index * cols + cols) : null
        const sel = selectionFor?.(r.day)
        return (
          <div key={v.key} style={{ position: 'absolute', top: r.top, left: 0, right: 0, height: tileH, display: 'flex', gap: GAP }}>
            {slice
              ? slice.map((it) => (
                <Tile key={it[0]} item={it} w={tileW} h={tileH}
                  state={sel ? (sel.exclude.has(it[0]) ? 'excluded' : sel.ids.has(it[0]) ? (sel.include.has(it[0]) ? 'included' : 'in') : 'out') : 'none'}
                  checked={selected.has(it[0])} selectMode={selectMode}
                  onClick={(e) => {
                    if (suppressClick.current) { suppressClick.current = false; return }
                    if (selectMode || e.metaKey || e.ctrlKey || e.shiftKey) toggle(it[0], e.shiftKey)
                    else onOpen(it[0])
                  }} />
              ))
              : Array.from({ length: Math.min(cols, r.kind === 'row' ? cols : 0) }).map((_, i) => (
                <div key={i} className="tile skeleton" style={{ width: tileW, height: tileH }} />
              ))}
          </div>
        )
      })}
      {rect && <div className="rubber" style={{ position: 'fixed', left: rect.x0, top: rect.y0, width: rect.x1 - rect.x0, height: rect.y1 - rect.y0 }} />}
    </div>
  )
})

type TileState = 'none' | 'in' | 'out' | 'included' | 'excluded'

const Tile = memo(function Tile({ item, w, h, state, checked, selectMode, onClick }: {
  item: Item; w: number; h: number; state: TileState; checked: boolean; selectMode: boolean
  onClick: (e: React.MouseEvent) => void
}) {
  const [url, setUrl] = useState<string | null | undefined>(() => thumbs.peek(item[0]))
  useEffect(() => {
    let alive = true
    if (url === undefined) thumbs.get(item[0], true).then((u) => { if (alive) setUrl(u) })
    return () => { alive = false }
  }, [item, url])
  const cls = 'tile' + (state === 'out' || state === 'excluded' ? ' dim' : '') + (checked ? ' checked' : '')
  return (
    <div className={cls} data-id={item[0]} style={{ width: w, height: h }} onClick={onClick}
      title={`${fmtTime(item[1])}${item[4] != null ? ` · Helligkeit ${Math.round(item[4])}` : ''}`}>
      {url ? <img src={url} alt="" draggable={false} /> : url === null ? <div className="tile-err">!</div> : null}
      {state === 'excluded' && <span className="tile-badge err">✕</span>}
      {state === 'included' && <span className="tile-badge ok">＋</span>}
      {(selectMode || checked) && <span className={'tile-check' + (checked ? ' on' : '')}>✓</span>}
      <span className="tile-time">{fmtTime(item[1]).slice(0, 5)}</span>
    </div>
  )
})
