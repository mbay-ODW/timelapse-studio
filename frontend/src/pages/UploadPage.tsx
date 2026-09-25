import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { fmtBytes, fmtNum } from '../lib/format'
import { toast, toastError } from '../components/Toast'

type Album = { source_id: number; name: string; images: number }
type Item = { file: File; status: 'wartet' | 'lädt' | 'fertig' | 'Fehler'; sent: number; error?: string; resumed?: boolean }

const EXT = /\.(jpe?g|png|webp|tiff?|heic|heif|zip)$/i
const PARALLEL = 3

/** Drag & Drop-Upload mit Fortschritt pro Datei und Resume (Q-3). */
export function UploadPage() {
  const [albums, setAlbums] = useState<Album[]>([])
  const [album, setAlbum] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [over, setOver] = useState(false)
  const [running, setRunning] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const itemsRef = useRef<Item[]>([])
  itemsRef.current = items
  const loadAlbums = () => api.get<Album[]>('/api/uploads/albums').then(setAlbums).catch(() => {})
  useEffect(() => { loadAlbums() }, [])

  const add = (files: FileList | File[]) => {
    const list = [...files].filter((f) => EXT.test(f.name))
    if (list.length < [...files].length) toast(`${[...files].length - list.length} Dateien übersprungen (Typ nicht unterstützt)`)
    setItems((x) => [...x, ...list.map((file) => ({ file, status: 'wartet' as const, sent: 0 }))])
  }
  const patch = (file: File, p: Partial<Item>) => setItems((x) => x.map((i) => (i.file === file ? { ...i, ...p } : i)))

  const uploadOne = async (it: Item, albumName: string) => {
    const f = it.file
    patch(f, { status: 'lädt' })
    try {
      const init = await api.post<{ upload_id: string; offset: number; chunk_size: number }>('/api/uploads/init', { album: albumName, filename: f.name, size: f.size })
      let off = init.offset
      if (off > 0) patch(f, { resumed: true, sent: off })
      while (off < f.size) {
        const chunk = f.slice(off, off + init.chunk_size)
        const r = await fetch(`/api/uploads/${init.upload_id}?offset=${off}`, { method: 'PUT', body: chunk })
        if (r.status === 409) { off = (await r.json()).detail.offset; continue }
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText)
        off = (await r.json()).offset
        patch(f, { sent: off })
      }
      patch(f, { status: 'fertig', sent: f.size })
    } catch (e) {
      patch(f, { status: 'Fehler', error: e instanceof Error ? e.message : String(e) })
    }
  }

  const start = async () => {
    const name = album.trim()
    if (!name) { toastError('Bitte einen Albumnamen angeben'); return }
    setRunning(true)
    const todo = itemsRef.current.filter((i) => i.status === 'wartet' || i.status === 'Fehler')
    let k = 0
    await Promise.all(Array.from({ length: PARALLEL }, async () => {
      while (k < todo.length) { const it = todo[k++]; await uploadOne(it, name) }
    }))
    setRunning(false)
    loadAlbums()
    const failed = itemsRef.current.filter((i) => i.status === 'Fehler').length
    if (failed) toastError(`${failed} Dateien fehlgeschlagen – erneut starten setzt fort`)
    else toast('Upload fertig – Bilder werden indexiert')
  }

  const total = items.reduce((a, i) => a + i.file.size, 0)
  const sent = items.reduce((a, i) => a + i.sent, 0)
  return (
    <div className="page stack">
      <h1>Upload</h1>
      <div className="card stack">
        <div className="row wrap">
          <label className="field grow">Album (wird eine eigene Quelle „Uploads/…“)
            <input list="albums" value={album} placeholder="z. B. Baustelle Garage" onChange={(e) => setAlbum(e.target.value)} />
            <datalist id="albums">{albums.map((a) => <option key={a.source_id} value={a.name} />)}</datalist>
          </label>
        </div>
        <div className={'dropzone' + (over ? ' over' : '')}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files) }}
          onClick={() => input.current?.click()}>
          <div style={{ fontSize: 28 }}>⇪</div>
          <div>Bilder oder ZIP-Archive hierher ziehen oder klicken</div>
          <div className="muted small">JPEG, PNG, WebP, HEIC, TIFF, ZIP · Abgebrochene Uploads setzen beim erneuten Hochladen derselben Datei fort</div>
          <input ref={input} type="file" multiple hidden accept=".jpg,.jpeg,.png,.webp,.tif,.tiff,.heic,.heif,.zip"
            onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = '' }} />
        </div>
        {items.length > 0 && (
          <>
            <div className="row wrap">
              <span className="grow small">{fmtNum(items.length)} Dateien · {fmtBytes(sent)} / {fmtBytes(total)}</span>
              <button disabled={running} onClick={() => setItems(items.filter((i) => i.status !== 'fertig'))}>Fertige ausblenden</button>
              <button disabled={running} onClick={() => setItems([])}>Liste leeren</button>
              <button className="primary" disabled={running || !items.some((i) => i.status !== 'fertig')} onClick={start}>{running ? 'lädt hoch…' : 'Hochladen'}</button>
            </div>
            <div className="progress"><div style={{ width: `${total ? (100 * sent) / total : 0}%` }} /></div>
            <div className="upload-list">
              {items.map((i, k) => (
                <div key={k} className="upload-item">
                  <span className="grow mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.file.name}</span>
                  <span className="muted small">{fmtBytes(i.file.size)}</span>
                  <div className="progress" style={{ width: 120 }}><div style={{ width: `${(100 * i.sent) / i.file.size}%` }} /></div>
                  <span className={'badge ' + (i.status === 'fertig' ? 'ok' : i.status === 'Fehler' ? 'err' : i.status === 'lädt' ? 'accent' : '')} title={i.error}>
                    {i.status}{i.resumed && i.status !== 'fertig' ? ' (fortgesetzt)' : ''}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      {albums.length > 0 && (
        <div className="card stack">
          <h2>Upload-Alben</h2>
          {albums.map((a) => <div key={a.source_id} className="row"><span className="grow">{a.name}</span><span className="muted small">{fmtNum(a.images)} Bilder</span></div>)}
          <div className="muted small">In einem Projekt über die Regel „Quellen“ auswählen. Verwaltung unter <Link to="/sources">Quellen</Link>.</div>
        </div>
      )}
    </div>
  )
}
