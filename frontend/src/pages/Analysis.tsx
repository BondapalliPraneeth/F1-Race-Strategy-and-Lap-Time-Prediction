import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { RaceSelector, useSelection } from '../components/RaceSelector'
import { Empty, ErrorBox, Panel, Spinner, Stat } from '../components/ui'
import { COLORS, fmtLap, useAsync } from '../lib'

export default function Analysis() {
  const { sel } = useSelection()
  const [cleanOnly, setCleanOnly] = useState(true)
  const key = sel.drivers.join(',')
  const cmp = useAsync(() => api.compare(sel.raceId!, sel.drivers), [sel.raceId, key], sel.raceId !== null && sel.drivers.length > 0)
  const pits = useAsync(() => api.pitStops(sel.raceId!), [sel.raceId], sel.raceId !== null)
  const weather = useAsync(() => api.weather(sel.raceId!), [sel.raceId], sel.raceId !== null)

  const rows = (() => {
    if (!cmp.data) return []
    const maxLap = Math.max(...cmp.data.drivers.flatMap((d) => d.laps.map((l) => l.lap_number)))
    return Array.from({ length: maxLap }, (_, i) => {
      const row: Record<string, number | null> = { lap: i + 1 }
      for (const d of cmp.data!.drivers) {
        const l = d.laps.find((x) => x.lap_number === i + 1)
        const excluded = cleanOnly && l && (l.is_in_lap || l.is_out_lap || l.is_neutralised || l.lap_number === 1)
        row[d.driver_id] = l && l.lap_time_ms && !excluded ? l.lap_time_ms : null
      }
      return row
    })
  })()

  return (
    <div className="page">
      <h1>Historical Race Analysis</h1>
      <p className="lede">Actual lap times, stints and pit stops read from the PostgreSQL database.</p>
      <RaceSelector mode="multi" />
      {!sel.raceId && <Empty title="Choose a season and Grand Prix to begin" />}
      {sel.race && (
        <div className="stats">
          <Stat label="Race" value={sel.race.name} sub={`${sel.race.season} · ${sel.race.circuit}`} />
          <Stat label="Distance" value={`${sel.race.total_laps} laps`} />
          <Stat label="Weather data" value={sel.race.data_availability.weather ? 'available' : 'not available'} />
          <Stat label="Tyre compound data" value={sel.race.data_availability.tyre_compound ? 'available' : 'not available'} sub="source limitation" />
        </div>
      )}
      {sel.raceId && sel.drivers.length === 0 && <Empty title="Select 1–4 drivers to compare" />}
      {cmp.loading && <Spinner label="Fetching laps…" />}
      {cmp.error && <ErrorBox error={cmp.error} onRetry={cmp.reload} />}
      {cmp.data && (
        <>
          <Panel title="Lap times" kind="actual" source="laps table (Jolpica-F1 timing data)"
            actions={<label className="inline"><input type="checkbox" checked={cleanOnly} onChange={(e) => setCleanOnly(e.target.checked)} /> Clean laps only</label>}>
            <div className="chart" data-testid="lap-chart">
              <ResponsiveContainer width="100%" height={360}>
                <LineChart data={rows} margin={{ left: 10, right: 20, top: 10 }}>
                  <CartesianGrid stroke="var(--grid)" />
                  <XAxis dataKey="lap" label={{ value: 'Lap', position: 'insideBottom', offset: -2 }} />
                  <YAxis domain={['auto', 'auto']} tickFormatter={fmtLap} width={70} />
                  <Tooltip formatter={(v) => fmtLap(Number(v))} labelFormatter={(l) => `Lap ${l}`} />
                  <Legend />
                  {cmp.data!.drivers.map((d, i) => <Line key={d.driver_id} dataKey={d.driver_id} stroke={COLORS[i]} dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />)}
                  {cmp.data!.drivers.flatMap((d, i) => (pits.data?.items ?? []).filter((p) => p.driver_id === d.driver_id).map((p) => {
                    const y = rows[p.lap - 1]?.[d.driver_id]
                    return y ? <ReferenceDot key={`${d.driver_id}${p.lap}`} x={p.lap} y={y} r={4} fill={COLORS[i]} stroke="#fff" /> : null
                  }))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="note">Dots mark pit-stop laps. Lap 1, in/out laps and detected safety-car laps are hidden when “clean laps only” is on.</p>
          </Panel>

          <Panel title="Driver &amp; stint comparison" kind="derived" source="stints derived from pit-stop records; compound not published by the source">
            <table>
              <thead><tr><th>Driver</th><th>Median clean lap</th><th>Clean laps</th><th>Stints (laps)</th><th>Pit stops</th></tr></thead>
              <tbody>
                {cmp.data.drivers.map((d, i) => (
                  <tr key={d.driver_id}>
                    <td><span className="swatch" style={{ background: COLORS[i] }} />{d.driver_id}</td>
                    <td>{fmtLap(d.median_clean_lap_ms)}</td>
                    <td>{d.n_clean_laps}</td>
                    <td>{d.stints.map((s) => `#${s.stint_number}: L${s.start_lap}–${s.end_lap}`).join('  ·  ')}</td>
                    <td>{(pits.data?.items ?? []).filter((p) => p.driver_id === d.driver_id).map((p) => `L${p.lap} (${p.duration_ms ? (p.duration_ms / 1000).toFixed(1) + 's' : '—'})`).join(', ') || 'none'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </>
      )}
      {sel.raceId && (
        <Panel title="Weather" kind="actual" source="weather table">
          {weather.loading ? <Spinner /> : weather.data?.available
            ? <p>{weather.data.items.length} weather samples loaded.</p>
            : <Empty title="No weather data for this race">{weather.data?.reason}</Empty>}
        </Panel>
      )}
    </div>
  )
}
