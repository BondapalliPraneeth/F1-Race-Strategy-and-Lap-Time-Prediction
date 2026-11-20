import { useState } from 'react'
import { CartesianGrid, Legend, Line, ComposedChart, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api'
import { RaceSelector, useSelection } from '../components/RaceSelector'
import { Empty, ErrorBox, Panel, Spinner, Stat } from '../components/ui'
import { COLORS, fmtLap, useAsync } from '../lib'

export default function Degradation() {
  const { sel } = useSelection()
  const [hidden, setHidden] = useState<number[]>([])
  const d = useAsync(() => api.degradation(sel.raceId!, sel.driver), [sel.raceId, sel.driver], sel.raceId !== null && sel.driver !== '')
  const stints = d.data?.stints ?? []
  const shown = stints.filter((s) => !hidden.includes(s.stint_number))

  return (
    <div className="page">
      <h1>Tyre Degradation</h1>
      <p className="lede">Per-stint degradation from actual laps. Fuel/track-evolution is removed using a race-wide regression with driver fixed effects.</p>
      <RaceSelector />
      {!sel.driver && <Empty title="Select a race and driver" />}
      {d.loading && <Spinner label="Fitting degradation models…" />}
      {d.error && <ErrorBox error={d.error} onRetry={d.reload} />}
      {d.data && !d.data.available && <Empty title="Degradation not available">{d.data.reason}</Empty>}
      {d.data?.available && (
        <>
          <div className="stats">
            <Stat label="Fuel / track-evolution slope" value={`${d.data.fuel_slope_ms_per_lap!.toFixed(1)} ms/lap`} sub="race-wide estimate, removed from the curves" />
            <Stat label="Pooled tyre degradation" value={`${d.data.pooled_degradation_ms_per_lap!.toFixed(1)} ± ${(1.96 * d.data.pooled_degradation_se!).toFixed(1)} ms/lap`} sub="95 % CI, all drivers in race" />
          </div>
          {d.data.notes?.map((n) => <p className="note warn" key={n}>ℹ {n}</p>)}
          <Panel title="Fuel-corrected lap time vs tyre age (per stint)" kind="derived" source="laps table; OLS fuel correction + per-stint linear fit"
            actions={<span className="chips-inline">{stints.map((s, i) => (
              <label key={s.stint_number} className="inline"><input type="checkbox" checked={!hidden.includes(s.stint_number)}
                onChange={() => setHidden((h) => (h.includes(s.stint_number) ? h.filter((x) => x !== s.stint_number) : [...h, s.stint_number]))} />
                <span className="swatch" style={{ background: COLORS[i % 6] }} />Stint {s.stint_number}</label>))}</span>}>
            <div className="chart" data-testid="deg-chart">
              <ResponsiveContainer width="100%" height={360}>
                <ComposedChart margin={{ left: 10, right: 20 }}>
                  <CartesianGrid stroke="var(--grid)" />
                  <XAxis type="number" dataKey="tyre_age" name="Tyre age" domain={[1, 'dataMax']} label={{ value: 'Tyre age (laps)', position: 'insideBottom', offset: -2 }} />
                  <YAxis type="number" dataKey="fuel_corrected_ms" domain={['auto', 'auto']} tickFormatter={fmtLap} width={70} />
                  <Tooltip formatter={(v) => fmtLap(Number(v))} />
                  <Legend />
                  {shown.map((s) => {
                    const i = stints.indexOf(s)
                    const ages = s.points.map((p) => p.tyre_age)
                    const line = s.slope_ms_per_lap != null && ages.length
                      ? [Math.min(...ages), Math.max(...ages)].map((a) => ({ tyre_age: a, fuel_corrected_ms: s.intercept_ms! + s.slope_ms_per_lap! * a })) : []
                    return [
                      <Scatter key={`p${s.stint_number}`} name={`Stint ${s.stint_number}${s.uncertain ? ' (uncertain)' : ''}`} data={s.points} fill={COLORS[i % 6]} fillOpacity={s.uncertain ? 0.45 : 1} isAnimationActive={false} />,
                      line.length ? <Line key={`l${s.stint_number}`} data={line} dataKey="fuel_corrected_ms" stroke={COLORS[i % 6]} dot={false} legendType="none" strokeDasharray={s.uncertain ? '5 4' : undefined} isAnimationActive={false} /> : null,
                    ]
                  })}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <p className="note">Dashed lines / faded points = uncertain stint (fewer than 5 clean laps, or slope not distinguishable from zero).</p>
          </Panel>
          <Panel title="Stint comparison" kind="derived" source="per-stint OLS with standard errors">
            <table>
              <thead><tr><th>Stint</th><th>Laps</th><th>Compound</th><th>Clean laps</th><th>Degradation</th><th>Status</th></tr></thead>
              <tbody>{stints.map((s, i) => (
                <tr key={s.stint_number}>
                  <td><span className="swatch" style={{ background: COLORS[i % 6] }} />#{s.stint_number}</td>
                  <td>L{s.start_lap}–{s.end_lap}</td>
                  <td>{s.compound ?? <em title="Compound is not published by the data source">unknown</em>}</td>
                  <td>{s.n_clean_laps}</td>
                  <td>{s.slope_ms_per_lap != null ? `${s.slope_ms_per_lap.toFixed(1)} ± ${(1.96 * s.slope_se!).toFixed(1)} ms/lap` : '—'}</td>
                  <td>{s.uncertain ? <span className="tag warn" title={s.uncertainty_reason ?? ''}>uncertain: {s.uncertainty_reason}</span> : <span className="tag ok">significant</span>}</td>
                </tr>))}</tbody>
            </table>
          </Panel>
          <Panel title="Model-implied degradation curve" kind="predicted" source={d.data.model_curve?.model_version ? `trained model v${d.data.model_curve.model_version}` : 'trained model'}>
            {d.data.model_curve?.points ? (
              <div className="chart"><ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={d.data.model_curve.points}>
                  <CartesianGrid stroke="var(--grid)" /><XAxis dataKey="tyre_age" /><YAxis domain={['auto', 'auto']} tickFormatter={fmtLap} width={70} />
                  <Tooltip formatter={(v) => fmtLap(Number(v))} />
                  <Line dataKey="predicted_ms" name={`Predicted at lap ${d.data.model_curve.at_lap}`} stroke="#38bdf8" strokeWidth={2} isAnimationActive={false} /><Legend />
                </ComposedChart></ResponsiveContainer></div>
            ) : <Empty title="Model curve unavailable">{d.data.model_curve?.reason}</Empty>}
          </Panel>
        </>
      )}
    </div>
  )
}
