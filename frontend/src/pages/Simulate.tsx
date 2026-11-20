import { useEffect, useState } from 'react'
import { DataContextPanel, useStrategyContext } from '../components/DataContext'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type ApiError, type SafetyCar, type SimResult, type Stint } from '../api'
import { initialForm, ParamsForm, toParams, validate } from '../components/ParamsForm'
import { RaceSelector, useSelection } from '../components/RaceSelector'
import { StintBar } from '../components/StintBar'
import { Badge, Empty, ErrorBox, Panel, Spinner } from '../components/ui'
import { COLORS, fmtRace, fmtSec } from '../lib'

/** "MEDIUM:25, HARD:30" -> stints; returns error text when invalid. */
export function parsePlan(text: string, compounds: string[], totalLaps: number | undefined): { stints?: Stint[]; error?: string } {
  const parts = text.split(',').map((s) => s.trim()).filter(Boolean)
  if (!parts.length) return { error: 'Enter at least one stint, e.g. MEDIUM:25, HARD:30' }
  const stints: Stint[] = []
  for (const p of parts) {
    const [c, n] = p.split(':').map((s) => s.trim())
    const laps = Number(n)
    if (!c || !compounds.includes(c.toUpperCase())) return { error: `Unknown compound "${c}" (use ${compounds.join('/')})` }
    if (!Number.isInteger(laps) || laps < 1) return { error: `"${p}": laps must be a whole number ≥ 1` }
    stints.push({ compound: c.toUpperCase(), laps })
  }
  const sum = stints.reduce((a, s) => a + s.laps, 0)
  if (totalLaps && sum !== totalLaps) return { error: `Stints add up to ${sum} laps but the race is ${totalLaps} laps` }
  return { stints }
}

export default function Simulate() {
  const { sel } = useSelection()
  const [form, setForm] = useState(initialForm)
  const ctx = useStrategyContext(sel.raceId)
  const dataDerived = ctx?.compound_profile_source === 'data'
  useEffect(() => { if (ctx?.compound_profile_source === 'data') setForm((f) => ({ ...f, compounds: ctx.compound_profiles })) }, [ctx])
  const [plans, setPlans] = useState<string[]>(['MEDIUM:25, HARD:30', 'SOFT:15, HARD:20, MEDIUM:20'])
  const [sc, setSc] = useState<SafetyCar>({ mode: 'random', probability: 0.3, duration_laps: 4, vsc: false, start_lap: 20 })
  const [rain, setRain] = useState({ on: false, start: '20', end: '30', slow: '6' })
  const [nSims, setNSims] = useState('2000')
  const [seed, setSeed] = useState('42')
  const [res, setRes] = useState<SimResult | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  const compounds = Object.keys(form.compounds)
  const total = sel.race?.total_laps
  const parsed = plans.map((p) => parsePlan(p, compounds, total))
  const formErrors = validate(form)
  const nErr = !(Number.isInteger(Number(nSims)) && Number(nSims) >= 1 && Number(nSims) <= 20000) ? 'Between 1 and 20 000' : null
  const ready = sel.raceId !== null && sel.driver !== '' && parsed.every((p) => !p.error) && !Object.keys(formErrors).length && !nErr

  async function loadRecommended() {
    setError(null)
    try {
      const o = await api.optimize({ race_id: sel.raceId!, driver_id: sel.driver, params: toParams(form) })
      const txt = (s: Stint[]) => s.map((x) => `${x.compound}:${x.laps}`).join(', ')
      setPlans([txt(o.recommended.stints), ...o.alternatives.filter((a) => a.label !== o.recommended.label).slice(0, 2).map((a) => txt(a.stints))])
    } catch (e) { setError(e as ApiError) }
  }

  async function run() {
    setBusy(true); setError(null)
    try {
      setRes(await api.simulate({
        race_id: sel.raceId, driver_id: sel.driver, params: toParams(form),
        strategies: parsed.map((p) => p.stints), safety_car: sc,
        weather: rain.on ? [{ start_lap: Number(rain.start), end_lap: Number(rain.end), slowdown_pct: Number(rain.slow) }] : [],
        n_sims: Number(nSims), seed: Number(seed) || 0,
      }))
    } catch (e) { setRes(null); setError(e as ApiError) } finally { setBusy(false) }
  }

  // overlay histograms on a shared x axis (bin centres, in minutes)
  const hist = (() => {
    if (!res) return []
    const all = res.strategies
    const lo = Math.min(...all.map((s) => s.histogram.edges_ms[0])), hi = Math.max(...all.map((s) => s.histogram.edges_ms.at(-1)!))
    const bins = 30, w = (hi - lo) / bins
    const rows = Array.from({ length: bins }, (_, i) => ({ x: lo + (i + 0.5) * w } as Record<string, number>))
    all.forEach((s, k) => s.histogram.counts.forEach((c, j) => {
      const centre = (s.histogram.edges_ms[j] + s.histogram.edges_ms[j + 1]) / 2
      const b = Math.min(bins - 1, Math.floor((centre - lo) / w)); rows[b][`s${k}`] = (rows[b][`s${k}`] ?? 0) + c
    }))
    return rows
  })()

  return (
    <div className="page">
      <h1>What-If Race Simulation</h1>
      <p className="lede">Monte Carlo over lap-time noise, pit-loss variation and optional safety-car / weather scenarios. Scenarios are <strong>hypothetical</strong> — not forecasts.</p>
      <RaceSelector />
      <Panel title="Strategies to compare" kind="assumption" source="user-entered plans; format COMPOUND:laps, comma separated">
        {plans.map((p, i) => (
          <div className="plan-row" key={i}>
            <label className="field"><span>Strategy {i + 1}</span>
              <input aria-label={`Strategy ${i + 1}`} value={p} onChange={(e) => setPlans(plans.map((x, j) => (j === i ? e.target.value : x)))} />
              <small className={parsed[i].error ? 'err' : ''} role={parsed[i].error ? 'alert' : undefined}>{parsed[i].error ?? `Valid · ${parsed[i].stints!.length - 1} stop(s)`}</small></label>
            {plans.length > 1 && <button type="button" onClick={() => setPlans(plans.filter((_, j) => j !== i))} aria-label={`Delete plan ${i + 1}`}>Remove</button>}
          </div>))}
        <div className="actions">
          {plans.length < 8 && <button type="button" onClick={() => setPlans([...plans, `MEDIUM:${Math.ceil((total ?? 50) / 2)}, HARD:${Math.floor((total ?? 50) / 2)}`])}>Add strategy</button>}
          <button type="button" disabled={!sel.driver} onClick={() => void loadRecommended()}>Load optimizer recommendation</button>
        </div>
      </Panel>
      <Panel title="Scenario & parameters" kind="assumption" source="hypothetical scenario inputs; seed makes runs reproducible">
        <div className="form-row">
          <label className="field"><span>Safety car</span>
            <select aria-label="Safety car mode" value={sc.mode} onChange={(e) => setSc({ ...sc, mode: e.target.value as SafetyCar['mode'] })}>
              <option value="none">None</option><option value="random">Random (probability)</option><option value="fixed">Fixed lap</option></select></label>
          {sc.mode === 'random' && <label className="field"><span>Probability per race</span>
            <input aria-label="SC probability" value={sc.probability} onChange={(e) => setSc({ ...sc, probability: Number(e.target.value) })} /></label>}
          {sc.mode === 'fixed' && <label className="field"><span>Start lap</span>
            <input aria-label="SC start lap" value={sc.start_lap} onChange={(e) => setSc({ ...sc, start_lap: Number(e.target.value) })} /></label>}
          {sc.mode !== 'none' && <label className="field"><span>Duration (laps)</span>
            <input aria-label="SC duration" value={sc.duration_laps} onChange={(e) => setSc({ ...sc, duration_laps: Number(e.target.value) })} /></label>}
          {sc.mode !== 'none' && <label className="field inline"><input type="checkbox" checked={sc.vsc} onChange={(e) => setSc({ ...sc, vsc: e.target.checked })} /> Virtual SC</label>}
        </div>
        <div className="form-row">
          <label className="field inline"><input type="checkbox" checked={rain.on} onChange={(e) => setRain({ ...rain, on: e.target.checked })} /> Weather window (hypothetical slowdown)</label>
          {rain.on && <>
            <label className="field"><span>From lap</span><input aria-label="Weather start" value={rain.start} onChange={(e) => setRain({ ...rain, start: e.target.value })} /></label>
            <label className="field"><span>To lap</span><input aria-label="Weather end" value={rain.end} onChange={(e) => setRain({ ...rain, end: e.target.value })} /></label>
            <label className="field"><span>Slowdown %</span><input aria-label="Weather slowdown" value={rain.slow} onChange={(e) => setRain({ ...rain, slow: e.target.value })} /></label></>}
          <label className="field"><span>Simulations</span><input aria-label="Simulations" value={nSims} onChange={(e) => setNSims(e.target.value)} />
            <small className={nErr ? 'err' : ''}>{nErr ?? 'max 20 000'}</small></label>
          <label className="field"><span>Random seed</span><input aria-label="Seed" value={seed} onChange={(e) => setSeed(e.target.value)} /></label>
        </div>
        <DataContextPanel ctx={ctx} />
        <ParamsForm value={form} onChange={setForm} dataDerived={dataDerived} />
        <div className="actions">
          <button className="primary" disabled={!ready || busy} onClick={() => void run()}>{busy ? 'Simulating…' : 'Run simulation'}</button>
          {!sel.driver && <span className="note">Select a race and driver first.</span>}
        </div>
      </Panel>

      {busy && <Spinner label={`Running ${nSims} simulations…`} />}
      {error && <ErrorBox error={error} />}
      {!res && !busy && !error && <Empty title="No simulation yet">Define strategies and run the simulation.</Empty>}
      {res && (
        <>
          <Panel title="Simulated race-time distribution" kind="simulated"
            source={`${res.n_sims} Monte Carlo runs, seed ${res.seed}, ${res.compute_seconds}s${res.scenario.hypothetical ? ' · hypothetical scenario' : ''}`}>
            <div className="chart" data-testid="sim-chart">
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={hist}><CartesianGrid stroke="var(--grid)" />
                  <XAxis dataKey="x" tickFormatter={(v) => fmtRace(Number(v))} minTickGap={40} /><YAxis allowDecimals={false} />
                  <Tooltip labelFormatter={(v) => fmtRace(Number(v))} /><Legend />
                  {res.strategies.map((s, i) => <Bar key={i} dataKey={`s${i}`} name={s.label} fill={COLORS[i % 6]} fillOpacity={0.6} isAnimationActive={false} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
            {res.scenario.safety_car.mode === 'random' && <p className="note">Safety car occurred in {(res.sc_hit_rate * 100).toFixed(0)} % of simulated races.</p>}
          </Panel>
          <Panel title="Strategy comparison" kind="simulated" source="same random draws for every strategy (common random numbers)">
            <table data-testid="sim-table">
              <thead><tr><th>Strategy</th><th>Mean</th><th>Median</th><th>P5 – P95</th><th>Std</th><th>Deterministic</th><th>Win prob.</th></tr></thead>
              <tbody>{res.strategies.map((s, i) => (
                <tr key={i}><td><span className="swatch" style={{ background: COLORS[i % 6] }} />{s.label}<StintBar stints={s.stints} /></td>
                  <td>{fmtRace(s.mean_ms)}</td><td>{fmtRace(s.median_ms)}</td><td>{fmtRace(s.p5_ms)} – {fmtRace(s.p95_ms)}</td>
                  <td>{fmtSec(s.std_ms)}</td><td>{fmtRace(s.deterministic_ms)}</td><td>{(s.win_probability * 100).toFixed(1)} %</td></tr>))}</tbody>
            </table>
            <p className="note"><Badge kind="simulated" /> Win probability = share of runs in which the strategy has the lowest total time among those compared.</p>
          </Panel>
        </>
      )}
    </div>
  )
}
