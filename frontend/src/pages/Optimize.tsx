import { useEffect, useState } from 'react'
import { api, type ApiError, type OptimizeResult } from '../api'
import { DataContextPanel, useStrategyContext } from '../components/DataContext'
import { initialForm, ParamsForm, toParams, validate } from '../components/ParamsForm'
import { RaceSelector, useSelection } from '../components/RaceSelector'
import { StintBar } from '../components/StintBar'
import { Badge, Empty, ErrorBox, Panel, Spinner, Stat } from '../components/ui'
import { fmtRace, fmtSec } from '../lib'

export default function Optimize() {
  const { sel } = useSelection()
  const [form, setForm] = useState(initialForm)
  const ctx = useStrategyContext(sel.raceId)
  const dataDerived = ctx?.compound_profile_source === 'data'
  useEffect(() => { if (ctx?.compound_profile_source === 'data') setForm((f) => ({ ...f, compounds: ctx.compound_profiles })) }, [ctx])
  const [res, setRes] = useState<OptimizeResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const errors = validate(form)
  const ready = sel.raceId !== null && sel.driver !== '' && Object.keys(errors).length === 0

  async function run() {
    setBusy(true); setError(null)
    try { setRes(await api.optimize({ race_id: sel.raceId!, driver_id: sel.driver, params: toParams(form) })) }
    catch (e) { setRes(null); setError(e as ApiError) }
    finally { setBusy(false) }
  }

  return (
    <div className="page">
      <h1>Pit-Stop Strategy Optimizer</h1>
      <p className="lede">Exact dynamic programming over all feasible stop counts, compound orders and pit laps, using the trained model’s predicted pace.</p>
      <RaceSelector />
      <DataContextPanel ctx={ctx} />
      <Panel title="Strategy parameters" kind={dataDerived ? 'derived' : 'assumption'} source="pit loss and stint limits estimated from recorded data unless overridden; other values are user-editable">
        <ParamsForm value={form} onChange={setForm} dataDerived={dataDerived} />
        <div className="actions">
          <button className="primary" disabled={!ready || busy} onClick={() => void run()}>{busy ? 'Optimizing…' : 'Find optimal strategy'}</button>
          {!sel.driver && <span className="note">Select a race and driver first.</span>}
        </div>
      </Panel>
      {busy && <Spinner label="Searching strategies…" />}
      {error && <ErrorBox error={error} />}
      {!res && !busy && !error && <Empty title="No result yet">Configure the parameters and run the optimizer.</Empty>}
      {res && (
        <>
          <Panel title="Recommended strategy" kind="predicted" source={`model v${res.model_version}; computed in ${res.compute_seconds}s`}>
            <div className="stats" data-testid="recommendation">
              <Stat label="Strategy" value={<span data-testid="recommended-label">{res.recommended.label}</span>} sub={`${res.recommended.stints.length - 1} stop(s)`} />
              <Stat label="Predicted race time" value={fmtRace(res.recommended.predicted_total_ms)} />
              <Stat label="Pit loss used" value={fmtSec(res.config.pit_loss_ms, 1)}
                sub={res.pit_loss_overridden ? 'user override' : `median of ${res.pit_loss_estimate.n_stops} recorded stops (${res.pit_loss_estimate.scope})`} />
              {res.actual_strategy.actual_total_ms && <Stat label="Actual race time (this driver)" value={fmtRace(res.actual_strategy.actual_total_ms)}
                sub={`actual stops: ${res.actual_strategy.pit_laps.join(', ') || 'none'}`} />}
            </div>
            <StintBar stints={res.recommended.stints} />
            <h4>Recommended pit windows</h4>
            <table data-testid="pit-windows">
              <thead><tr><th>Stop</th><th>Optimal lap</th><th>Window (≤ tolerance from optimum)</th></tr></thead>
              <tbody>{res.recommended.pit_windows.map((w) => <tr key={w.stop}><td>{w.stop}</td><td>{w.optimal_lap}</td><td>laps {w.earliest}–{w.latest}</td></tr>)}
                {res.recommended.pit_windows.length === 0 && <tr><td colSpan={3}>No-stop strategy</td></tr>}</tbody>
            </table>
            <h4>Why this recommendation</h4>
            <ul className="explain" data-testid="explanation">{res.explanation.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </Panel>
          <Panel title="Alternatives" kind="predicted" source="same optimizer, ranked by predicted total time">
            <table>
              <thead><tr><th>Strategy</th><th>Stints</th><th>Predicted time</th><th>Δ vs best</th></tr></thead>
              <tbody>{res.alternatives.map((a) => (
                <tr key={a.label}><td>{a.label}</td><td style={{ minWidth: 220 }}><StintBar stints={a.stints} /></td>
                  <td>{fmtRace(a.predicted_total_ms)}</td><td>+{fmtSec(a.predicted_total_ms - res.recommended.predicted_total_ms)}</td></tr>))}</tbody>
            </table>
          </Panel>
          <p className="note warn"><Badge kind="assumption" /> {res.assumption_notes.join(' ')}</p>
        </>
      )}
    </div>
  )
}
