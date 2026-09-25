import type { Job } from './types'

/** Browser-Benachrichtigung bei Job-Ende (R-6), nur wenn der Tab nicht im Vordergrund ist. */
const seen = new Map<number, string>()
let primed = false

export function requestNotifyPermission() {
  try { if ('Notification' in window && Notification.permission === 'default') void Notification.requestPermission() } catch { /* ignore */ }
}

export function checkJobTransitions(jobs: Job[]) {
  for (const j of jobs) {
    const prev = seen.get(j.id)
    seen.set(j.id, j.status)
    if (!primed || !prev || prev === j.status) continue
    if ((prev === 'rendering' || prev === 'preparing') && ['done', 'failed'].includes(j.status) && j.kind === 'render') {
      try {
        if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
          new Notification(j.status === 'done' ? `Zeitraffer fertig: ${j.project_name}` : `Render fehlgeschlagen: ${j.project_name}`,
            { body: j.status === 'done' ? j.output_name ?? '' : j.error ?? '', icon: '/favicon.svg' })
        }
      } catch { /* ignore */ }
    }
  }
  primed = true
}
