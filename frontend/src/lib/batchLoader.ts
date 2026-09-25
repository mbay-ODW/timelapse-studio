/**
 * Bündelt Einzelanfragen für Thumbnails/Proxies zu Batch-Requests (/api/thumbs?ids=…).
 * Hintergrund: Traefik-Ratelimit mit geteiltem LAN-Bucket + Authelia-Check pro Request.
 * Hält Blob-URLs in einem LRU-Cache und gibt verdrängte wieder frei.
 */
type Waiter = { resolve: (url: string | null) => void }

export class BatchLoader {
  private cache = new Map<number, string | null>()
  private waiting = new Map<number, Waiter[]>()
  private queue: number[] = []
  private timer: number | null = null
  private inFlight = 0
  private readonly endpoint: string
  private readonly batchSize: number
  private readonly maxCache: number
  private readonly maxParallel: number
  private readonly mime: string

  constructor(endpoint: string, opts: { batchSize?: number; maxCache?: number; maxParallel?: number; mime: string }) {
    this.endpoint = endpoint
    this.batchSize = opts.batchSize ?? 120
    this.maxCache = opts.maxCache ?? 4000
    this.maxParallel = opts.maxParallel ?? 3
    this.mime = opts.mime
  }

  peek(id: number): string | null | undefined {
    const v = this.cache.get(id)
    if (v !== undefined) { this.cache.delete(id); this.cache.set(id, v) } // LRU-Touch
    return v
  }

  get(id: number, priority = false): Promise<string | null> {
    const hit = this.peek(id)
    if (hit !== undefined) return Promise.resolve(hit)
    return new Promise((resolve) => {
      const w = this.waiting.get(id)
      if (w) { w.push({ resolve }); return }
      this.waiting.set(id, [{ resolve }])
      if (priority) this.queue.unshift(id)
      else this.queue.push(id)
      this.schedule()
    })
  }

  /** Nur vorladen, ohne auf das Ergebnis zu warten. */
  prefetch(ids: number[]) {
    for (const id of ids) if (!this.cache.has(id) && !this.waiting.has(id)) void this.get(id)
  }

  /** Wartende, noch nicht gesendete Anfragen verwerfen (z. B. nach schnellem Scrollen). */
  cancelPending(keep: Set<number>) {
    const drop = this.queue.filter((id) => !keep.has(id))
    this.queue = this.queue.filter((id) => keep.has(id))
    for (const id of drop) {
      this.waiting.get(id)?.forEach((w) => w.resolve(null))
      this.waiting.delete(id)
    }
  }

  private schedule() {
    if (this.timer != null) return
    this.timer = window.setTimeout(() => { this.timer = null; this.pump() }, 12)
  }

  private pump() {
    while (this.queue.length && this.inFlight < this.maxParallel) {
      const ids = this.queue.splice(0, this.batchSize)
      this.inFlight++
      this.fetchBatch(ids).finally(() => { this.inFlight--; this.pump() })
    }
  }

  private async fetchBatch(ids: number[]) {
    try {
      const res = await fetch(`${this.endpoint}?ids=${ids.join(',')}`)
      if (!res.ok) throw new Error(String(res.status))
      const buf = await res.arrayBuffer()
      const view = new DataView(buf)
      const hlen = view.getUint32(0, true)
      const header: [number, number][] = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)))
      let off = 4 + hlen
      for (const [id, len] of header) {
        const url = len > 0 ? URL.createObjectURL(new Blob([new Uint8Array(buf, off, len)], { type: this.mime })) : null
        off += len
        this.store(id, url)
      }
    } catch {
      // Fehler: Wartende mit null bedienen, aber nicht cachen → späterer Retry möglich
      for (const id of ids) {
        this.waiting.get(id)?.forEach((w) => w.resolve(null))
        this.waiting.delete(id)
      }
    }
  }

  private store(id: number, url: string | null) {
    this.cache.set(id, url)
    this.waiting.get(id)?.forEach((w) => w.resolve(url))
    this.waiting.delete(id)
    while (this.cache.size > this.maxCache) {
      const [oldId, oldUrl] = this.cache.entries().next().value as [number, string | null]
      this.cache.delete(oldId)
      if (oldUrl) URL.revokeObjectURL(oldUrl)
    }
  }
}

export const thumbs = new BatchLoader('/api/thumbs', { mime: 'image/webp', batchSize: 150, maxCache: 5000 })
export const previews = new BatchLoader('/api/previews', { mime: 'image/jpeg', batchSize: 40, maxCache: 1500, maxParallel: 2 })
