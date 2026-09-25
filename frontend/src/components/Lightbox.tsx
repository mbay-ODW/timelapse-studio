import { useEffect, useState } from 'react'
import { api, originalUrl, previewUrl } from '../lib/api'
import { fmtBytes, fmtDateTime } from '../lib/format'

type Meta = {
  id: number; source: string; path: string; taken_ms: number; ts_origin: string; width: number | null
  height: number | null; size: number; brightness: number | null; error: string | null
}

const ORIGIN: Record<string, string> = { exif: 'EXIF', filename: 'Dateiname', mtime: 'Änderungsdatum' }

/** Vollbild mit Pfeiltasten und Metadaten (B-4). */
export function Lightbox({ ids, index, onIndex, onClose, actions }: {
  ids: number[]; index: number; onIndex: (i: number) => void; onClose: () => void
  actions?: (id: number) => React.ReactNode
}) {
  const id = ids[index]
  const [meta, setMeta] = useState<Meta | null>(null)
  const [full, setFull] = useState(false)
  useEffect(() => { setFull(false); api.get<Meta>(`/api/images/${id}`).then(setMeta).catch(() => setMeta(null)) }, [id])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight' && index < ids.length - 1) onIndex(index + 1)
      else if (e.key === 'ArrowLeft' && index > 0) onIndex(index - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, ids.length, onIndex, onClose])
  // Nachbarn vorladen
  useEffect(() => {
    for (const j of [index + 1, index - 1, index + 2]) if (ids[j]) { const im = new Image(); im.src = previewUrl(ids[j]) }
  }, [index, ids])

  return (
    <div className="lightbox" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="lb-top">
        <span>{meta ? fmtDateTime(meta.taken_ms) : ''}</span>
        <span className="muted small">{index + 1} / {ids.length}</span>
        <div className="spacer" />
        {actions?.(id)}
        <button className={full ? 'active' : ''} onClick={() => setFull(!full)} title="Originalauflösung laden">Original</button>
        <button onClick={onClose} title="Schließen (Esc)">✕</button>
      </div>
      <div className="lb-stage" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
        {index > 0 && <button className="lb-nav left" onClick={() => onIndex(index - 1)}>‹</button>}
        <img src={full ? originalUrl(id) : previewUrl(id)} alt="" />
        {index < ids.length - 1 && <button className="lb-nav right" onClick={() => onIndex(index + 1)}>›</button>}
      </div>
      {meta && (
        <div className="lb-meta small">
          <span>{meta.width && meta.height ? `${meta.width} × ${meta.height}` : '–'}</span>
          <span>Helligkeit {meta.brightness != null ? Math.round(meta.brightness) : '–'}</span>
          <span>{fmtBytes(meta.size)}</span>
          <span>Zeit aus {ORIGIN[meta.ts_origin] ?? meta.ts_origin}</span>
          <span className="mono">{meta.source}/{meta.path}</span>
        </div>
      )}
    </div>
  )
}
