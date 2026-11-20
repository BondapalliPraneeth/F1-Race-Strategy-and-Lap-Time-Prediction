import type { CompoundProfile, StrategyParams } from '../api'
import { Badge } from './ui'

export const DEFAULT_COMPOUNDS: Record<string, CompoundProfile> = {
  SOFT: { offset_ms: -600, degradation_multiplier: 1.8, max_stint_laps: 20 },
  MEDIUM: { offset_ms: 0, degradation_multiplier: 1.0, max_stint_laps: 32 },
  HARD: { offset_ms: 450, degradation_multiplier: 0.6, max_stint_laps: 45 },
}

export interface FormState {
  pitLoss: string; maxStops: string; minCompounds: string; minStint: string
  trafficMs: string; trafficLaps: string; compounds: Record<string, CompoundProfile>
}
export const initialForm = (): FormState => ({
  pitLoss: '', maxStops: '3', minCompounds: '2', minStint: '5', trafficMs: '0', trafficLaps: '0',
  compounds: JSON.parse(JSON.stringify(DEFAULT_COMPOUNDS)),
})

/** Returns validation messages keyed by field; empty object when valid. */
export function validate(f: FormState): Record<string, string> {
  const e: Record<string, string> = {}
  const num = (v: string) => (v.trim() === '' ? NaN : Number(v))
  if (f.pitLoss !== '' && !(num(f.pitLoss) >= 5 && num(f.pitLoss) <= 60)) e.pitLoss = 'Pit loss must be 5–60 s (leave blank to use the data-derived value)'
  if (!(Number.isInteger(num(f.maxStops)) && num(f.maxStops) >= 0 && num(f.maxStops) <= 4)) e.maxStops = 'Whole number 0–4'
  if (!(Number.isInteger(num(f.minCompounds)) && num(f.minCompounds) >= 1 && num(f.minCompounds) <= Object.keys(f.compounds).length)) e.minCompounds = 'Between 1 and the number of compounds'
  if (!(Number.isInteger(num(f.minStint)) && num(f.minStint) >= 1 && num(f.minStint) <= 30)) e.minStint = 'Whole number 1–30'
  for (const [c, p] of Object.entries(f.compounds)) {
    if (!(p.max_stint_laps >= 5 && p.max_stint_laps <= 100)) e[`${c}.max`] = `${c}: max stint 5–100`
    if (!(p.degradation_multiplier >= 0.2 && p.degradation_multiplier <= 4)) e[`${c}.deg`] = `${c}: multiplier 0.2–4`
  }
  return e
}

export function toParams(f: FormState): StrategyParams {
  const p: StrategyParams = {
    max_stops: Number(f.maxStops), min_compounds_used: Number(f.minCompounds), min_stint_laps: Number(f.minStint),
    compounds: f.compounds, traffic_penalty_ms: Number(f.trafficMs) || 0, traffic_laps: Number(f.trafficLaps) || 0,
  }
  if (f.pitLoss !== '') p.pit_loss_ms = Number(f.pitLoss) * 1000
  return p
}

export function ParamsForm({ value, onChange, dataDerived = false }: { value: FormState; onChange: (v: FormState) => void; dataDerived?: boolean }) {
  const errors = validate(value)
  const set = (k: keyof FormState, v: string) => onChange({ ...value, [k]: v })
  const setC = (c: string, k: keyof CompoundProfile, v: string) =>
    onChange({ ...value, compounds: { ...value.compounds, [c]: { ...value.compounds[c], [k]: Number(v) } } })
  return (
    <div className="params">
      <div className="form-row">
        <label className="field"><span>Pit-lane time loss (s)</span>
          <input aria-label="Pit loss seconds" placeholder="data-derived" value={value.pitLoss} onChange={(e) => set('pitLoss', e.target.value)} />
          <small className={errors.pitLoss ? 'err' : ''}>{errors.pitLoss ?? 'Blank = estimated from this circuit’s recorded stops'}</small></label>
        <label className="field"><span>Max stops</span>
          <input aria-label="Max stops" value={value.maxStops} onChange={(e) => set('maxStops', e.target.value)} />
          <small className={errors.maxStops ? 'err' : ''}>{errors.maxStops ?? 'Simplified assumption'}</small></label>
        <label className="field"><span>Min different compounds</span>
          <input aria-label="Min compounds" value={value.minCompounds} onChange={(e) => set('minCompounds', e.target.value)} />
          <small className={errors.minCompounds ? 'err' : ''}>{errors.minCompounds ?? 'FIA dry-race rule: 2'}</small></label>
        <label className="field"><span>Min stint (laps)</span>
          <input aria-label="Min stint" value={value.minStint} onChange={(e) => set('minStint', e.target.value)} />
          <small className={errors.minStint ? 'err' : ''}>{errors.minStint ?? 'Assumption'}</small></label>
        <label className="field"><span>Traffic cost after stop (ms/lap × laps)</span>
          <span className="pair"><input aria-label="Traffic ms" value={value.trafficMs} onChange={(e) => set('trafficMs', e.target.value)} />
            <input aria-label="Traffic laps" value={value.trafficLaps} onChange={(e) => set('trafficLaps', e.target.value)} /></span>
          <small>Assumption; 0 = clean air</small></label>
      </div>
      <details open>
        <summary>Compound profiles {dataDerived
          ? <><Badge kind="derived" /> — max stint = 90th percentile of real stints on this compound; pace comes from the model, so offset 0 / multiplier 1 (editable what-ifs)</>
          : <><Badge kind="assumption" /> — no tyre data for this model, so these are editable hypotheses</>}</summary>
        <table className="compact">
          <thead><tr><th>Compound</th><th>Pace offset (ms/lap)</th><th>Degradation ×</th><th>Max stint (laps)</th></tr></thead>
          <tbody>{Object.entries(value.compounds).map(([c, p]) => (
            <tr key={c}><td>{c}</td>
              <td><input aria-label={`${c} offset`} value={p.offset_ms} onChange={(e) => setC(c, 'offset_ms', e.target.value)} /></td>
              <td><input aria-label={`${c} degradation multiplier`} value={p.degradation_multiplier} onChange={(e) => setC(c, 'degradation_multiplier', e.target.value)} /></td>
              <td><input aria-label={`${c} max stint`} value={p.max_stint_laps} onChange={(e) => setC(c, 'max_stint_laps', e.target.value)} /></td></tr>))}</tbody>
        </table>
        {Object.entries(errors).filter(([k]) => k.includes('.')).map(([k, m]) => <small className="err" key={k} role="alert">{m}</small>)}
      </details>
    </div>
  )
}
