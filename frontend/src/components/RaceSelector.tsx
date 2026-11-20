import { useSearchParams } from 'react-router-dom'
import { api, type RaceDetail } from '../api'
import { useAsync } from '../lib'
import { Empty, ErrorBox, Field, Spinner } from './ui'

export interface Selection {
  season: number | null
  raceId: number | null
  driver: string
  drivers: string[]
  race: RaceDetail | null
}

/** URL-backed selection state: season -> Grand Prix -> session -> driver(s). Shareable links, back/forward work. */
export function useSelection(): { sel: Selection; set: (k: Record<string, string | null>) => void; loading: boolean } {
  const [sp, setSp] = useSearchParams()
  const raceId = sp.get('race') ? Number(sp.get('race')) : null
  const race = useAsync(() => api.race(raceId!), [raceId], raceId !== null)
  const drivers = (sp.get('drivers') ?? '').split(',').filter(Boolean)
  const set = (k: Record<string, string | null>) => {
    const next = new URLSearchParams(sp)
    for (const [key, v] of Object.entries(k)) v === null || v === '' ? next.delete(key) : next.set(key, v)
    setSp(next, { replace: true })
  }
  return {
    sel: { season: sp.get('season') ? Number(sp.get('season')) : null, raceId, driver: sp.get('driver') ?? '', drivers, race: race.data },
    set,
    loading: race.loading,
  }
}

export function RaceSelector({ mode = 'single' }: { mode?: 'single' | 'multi' | 'none' }) {
  const { sel, set, loading } = useSelection()
  const seasons = useAsync(() => api.seasons(), [])
  const races = useAsync(() => api.races(sel.season ?? undefined), [sel.season], sel.season !== null)

  if (seasons.loading) return <Spinner label="Loading seasons…" />
  if (seasons.error) return <ErrorBox error={seasons.error} onRetry={seasons.reload} />
  if (!seasons.data?.length)
    return <Empty title="No race data in the database">Run the ingestion pipeline first: <code>python -m app.cli ingest --season 2024</code></Empty>

  const toggle = (id: string) => {
    const has = sel.drivers.includes(id)
    const next = has ? sel.drivers.filter((d) => d !== id) : [...sel.drivers, id].slice(-4)
    set({ drivers: next.join(',') })
  }

  return (
    <div className="selector" role="group" aria-label="Race selection">
      <Field label="Season">
        <select aria-label="Season" value={sel.season ?? ''} onChange={(e) => set({ season: e.target.value, race: null, driver: null, drivers: null })}>
          <option value="">Select season…</option>
          {seasons.data.map((s) => <option key={s.season} value={s.season}>{s.season} ({s.races} races)</option>)}
        </select>
      </Field>
      <Field label="Grand Prix">
        <select aria-label="Grand Prix" value={sel.raceId ?? ''} disabled={!sel.season || races.loading}
          onChange={(e) => set({ race: e.target.value, driver: null, drivers: null })}>
          <option value="">{races.loading ? 'Loading…' : 'Select Grand Prix…'}</option>
          {races.data?.items.map((r) => <option key={r.id} value={r.id}>R{r.round} · {r.name}</option>)}
        </select>
      </Field>
      <Field label="Session" hint={sel.race ? 'Only the race session is available from the data source' : undefined}>
        <select aria-label="Session" value="race" disabled={!sel.race} onChange={() => undefined}>
          {(sel.race?.sessions ?? [{ key: 'race', label: 'Race', available: true }]).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
      </Field>
      {mode === 'single' && (
        <Field label="Driver">
          <select aria-label="Driver" value={sel.driver} disabled={!sel.race} onChange={(e) => set({ driver: e.target.value })}>
            <option value="">{loading ? 'Loading…' : 'Select driver…'}</option>
            {sel.race?.drivers.map((d) => <option key={d.driver_id} value={d.driver_id}>{d.code ?? d.driver_id} · {d.name} (P{d.position ?? '–'})</option>)}
          </select>
        </Field>
      )}
      {mode === 'multi' && sel.race && (
        <fieldset className="chips">
          <legend>Drivers to compare (max 4)</legend>
          {sel.race.drivers.map((d) => (
            <label key={d.driver_id} className={sel.drivers.includes(d.driver_id) ? 'chip on' : 'chip'}>
              <input type="checkbox" checked={sel.drivers.includes(d.driver_id)} onChange={() => toggle(d.driver_id)} />
              {d.code ?? d.driver_id}
            </label>
          ))}
        </fieldset>
      )}
    </div>
  )
}
