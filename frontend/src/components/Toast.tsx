import { useEffect, useState } from 'react'

type T = { id: number; text: string; err?: boolean }
let push: (t: Omit<T, 'id'>) => void = () => {}
let seq = 0

export const toast = (text: string) => push({ text })
export const toastError = (e: unknown) => push({ text: e instanceof Error ? e.message : String(e), err: true })

export function Toasts() {
  const [items, setItems] = useState<T[]>([])
  useEffect(() => {
    push = (t) => {
      const id = ++seq
      setItems((x) => [...x, { ...t, id }])
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.err ? 7000 : 3500)
    }
  }, [])
  return (
    <div className="toast-wrap">
      {items.map((t) => <div key={t.id} className={'toast' + (t.err ? ' err' : '')}>{t.text}</div>)}
    </div>
  )
}
