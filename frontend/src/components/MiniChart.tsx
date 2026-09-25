import { fmtDate } from '../lib/format'

/** Verteilung der Auswahl pro Tag (S-20). */
export function MiniChart({ data, height = 36 }: { data: [number, number][]; height?: number }) {
  if (!data.length) return <div className="muted small">keine Bilder</div>
  const t0 = data[0][0], t1 = data[data.length - 1][0] + 86_400_000
  const max = Math.max(...data.map((d) => d[1]))
  const span = t1 - t0
  const bw = Math.max(0.5, (86_400_000 / span) * 100 * 0.8)
  return (
    <svg className="minichart" viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: '100%', height }}>
      <title>{`${fmtDate(t0)} – ${fmtDate(t1 - 86_400_000)}, max. ${max} pro Tag`}</title>
      {data.map(([t, n]) => {
        const h = Math.max(1, (n / max) * height)
        return <rect key={t} x={((t - t0) / span) * 100} y={height - h} width={bw} height={h} />
      })}
    </svg>
  )
}
