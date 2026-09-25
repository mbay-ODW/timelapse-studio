// Zeitwerte kommen als "naive Epoch-ms" (Lokalzeit als UTC kodiert) → immer mit timeZone UTC formatieren.
const dtf = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('de-DE', { timeZone: 'UTC', ...opts })
const fDate = dtf({ day: '2-digit', month: '2-digit', year: 'numeric' })
const fDateLong = dtf({ weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })
const fTime = dtf({ hour: '2-digit', minute: '2-digit', second: '2-digit' })
const fMonth = dtf({ month: 'short', year: 'numeric' })

export const fmtDate = (ms: number) => fDate.format(ms)
export const fmtDateLong = (ms: number) => fDateLong.format(ms)
export const fmtTime = (ms: number) => fTime.format(ms)
export const fmtDateTime = (ms: number) => `${fDate.format(ms)} ${fTime.format(ms)}`
export const fmtMonth = (ms: number) => fMonth.format(ms)
export const dayToMs = (day: string) => Date.parse(day + 'T00:00:00Z')
export const msToDay = (ms: number) => new Date(ms).toISOString().slice(0, 10)

export const fmtNum = (n: number) => n.toLocaleString('de-DE')

export function fmtDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return '–'
  s = Math.max(0, Math.round(s))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')} h`
  return `${m}:${String(sec).padStart(2, '0')} min`
}

export function fmtBytes(b: number | null | undefined): string {
  if (b == null) return '–'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++ }
  return `${b.toLocaleString('de-DE', { maximumFractionDigits: i ? 1 : 0 })} ${u[i]}`
}
