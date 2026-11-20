import { useEffect, useState } from 'react'
import { api, type StrategyContext } from '../api'
import { Panel } from './ui'

/** Loads real tyre / weather / safety-car evidence for a race. `null` while loading or when unavailable. */
export function useStrategyContext(raceId: number | null): StrategyContext | null {
  const [ctx, setCtx] = useState<StrategyContext | null>(null)
  useEffect(() => {
    setCtx(null)
    if (raceId === null) return
    let live = true
    api.strategyContext(raceId).then((c) => { if (live) setCtx(c) }).catch(() => { if (live) setCtx(null) })
    return () => { live = false }
  }, [raceId])
  return ctx
}

const pct = (x?: number | null) => (x == null ? '—' : `${(x * 100).toFixed(0)}%`)

export function DataContextPanel({ ctx }: { ctx: StrategyContext | null }) {
  if (!ctx) return null
  const { safety_car: sc, weather: wx } = ctx
  return (
    <Panel title="Real tyre, weather and safety-car data" kind="actual" source="Mendeley FastF1-derived dataset (CC BY 4.0), joined onto Jolpica laps">
      <div data-testid="data-context">
        <h4>Stint lengths on each compound</h4>
        <table className="compact">
          <thead><tr><th>Compound</th><th>Stints</th><th>Median</th><th>P90 (used as max stint)</th><th>Longest</th><th>Scope</th></tr></thead>
          <tbody>{Object.entries(ctx.compound_evidence).map(([c, e]) => (
            <tr key={c}><td>{c}</td><td>{e.n_stints}</td><td>{e.median_stint_laps}</td><td>{e.p90_stint_laps}</td><td>{e.longest_stint_laps}</td>
              <td>{e.scope === 'circuit' ? 'this circuit' : 'all circuits'}</td></tr>))}</tbody>
        </table>
        <h4>Safety car</h4>
        {sc.available
          ? <p>{pct(sc.sc_probability)} of races had a safety car (mean {sc.sc_mean_laps_per_period?.toFixed(1) ?? '—'} laps) and {pct(sc.vsc_probability)} a virtual
            safety car, over {sc.n_races} races ({sc.scope === 'circuit' ? 'this circuit' : 'all circuits'}).</p>
          : <p className="note">{sc.reason}</p>}
        <h4>Weather in this race</h4>
        {wx.available && wx.air_temp_c && wx.track_temp_c
          ? <p>Air {wx.air_temp_c.mean.toFixed(1)} °C · track {wx.track_temp_c.mean.toFixed(1)} °C (max {wx.track_temp_c.max.toFixed(1)}) · humidity {wx.humidity_pct_mean?.toFixed(0) ?? '—'}% ·
            rain on {pct(wx.rain_lap_share)} of laps.</p>
          : <p className="note">{wx.reason}</p>}
        <p className="note">
          {ctx.model_uses_compound
            ? 'The model was trained with compound as a feature. Observed compound pace is confounded by strategy and fuel load, so treat compound differences as associations, not tyre physics.'
            : 'The active model does not use compound.'}
        </p>
      </div>
    </Panel>
  )
}
