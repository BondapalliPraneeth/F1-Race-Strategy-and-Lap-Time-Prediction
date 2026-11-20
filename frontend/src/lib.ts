import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export const fmtLap = (ms: number | null | undefined) => {
  if (ms == null) return '—'
  const m = Math.floor(ms / 60000)
  return `${m}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}`
}
export const fmtRace = (ms: number | null | undefined) => {
  if (ms == null) return '—'
  const h = Math.floor(ms / 3600000)
  const rest = ms - h * 3600000
  return `${h}:${fmtLap(rest).padStart(9, '0')}`
}
export const fmtSec = (ms: number, d = 2) => `${(ms / 1000).toFixed(d)} s`
export const COLORS = ['#e10600', '#38bdf8', '#facc15', '#4ade80', '#c084fc', '#fb923c']
export const COMPOUND_COLORS: Record<string, string> = { SOFT: '#ef4444', MEDIUM: '#facc15', HARD: '#e5e7eb', INTERMEDIATE: '#4ade80', WET: '#38bdf8' }

export interface AsyncState<T> { data: T | null; error: ApiError | null; loading: boolean; reload: () => void }

/** Runs ``fn`` whenever ``deps`` change; ``enabled=false`` keeps the state idle. Stale responses are ignored. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], enabled = true): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean }>({ data: null, error: null, loading: enabled })
  const seq = useRef(0)
  const [tick, setTick] = useState(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps)
  useEffect(() => {
    if (!enabled) { setState({ data: null, error: null, loading: false }); return }
    const id = ++seq.current
    setState((s) => ({ ...s, loading: true, error: null }))
    run().then(
      (data) => id === seq.current && setState({ data, error: null, loading: false }),
      (error) => id === seq.current && setState({ data: null, error: error instanceof ApiError ? error : new ApiError(0, String(error)), loading: false }),
    )
  }, [run, enabled, tick])
  return { ...state, reload: () => setTick((t) => t + 1) }
}
