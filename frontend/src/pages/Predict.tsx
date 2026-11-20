import { useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, ApiError, type Prediction } from '../api'
import { RaceSelector, useSelection } from '../components/RaceSelector'
import { Empty, ErrorBox, Field, Panel, Spinner, Stat } from '../components/ui'
import { fmtLap, useAsync } from '../lib'

const SPLIT_TEXT: Record<string, string> = {
  held_out_test: 'Held-out test race — the model never saw this race in training (honest accuracy).',
  training: 'Training race — the model was fitted on this race, so errors here are optimistic.',
  not_in_model_data: 'Race not part of the model’s data.',
}

export default function Predict() {
  const { sel } = useSelection()
  const [lap, setLap] = useState('20')
  const [age, setAge] = useState('5')
  const [compound, setCompound] = useState('')
  const [result, setResult] = useState<Prediction | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  const lapN = Number(lap), ageN = Number(age)
  const lapErr = !Number.isInteger(lapN) || lapN < 1 || lapN > (sel.race?.total_laps ?? 100) ? `Enter a whole lap between 1 and ${sel.race?.total_laps ?? 100}` : null
  const ageErr = !Number.isInteger(ageN) || ageN < 1 ? 'Enter a whole number ≥ 1' : ageN > lapN ? 'Tyre age cannot exceed the lap number' : null
  const ready = sel.raceId !== null && sel.driver !== '' && !lapErr && !ageErr

  const pva = useAsync(() => api.pva(sel.raceId!, sel.driver), [sel.raceId, sel.driver], sel.raceId !== null && sel.driver !== '')

  async function run() {
    setBusy(true); setError(null)
    try { setResult(await api.predict({ race_id: sel.raceId!, driver_id: sel.driver, lap_number: lapN, tyre_age: ageN, compound: compound || undefined })) }
    catch (e) { setResult(null); setError(e as ApiError) }
    finally { setBusy(false) }
  }

  return (
    <div className="page">
      <h1>Lap-Time Prediction</h1>
      <p className="lede">A trained gradient-boosted quantile model predicts the lap time with an 80 % prediction interval.</p>
      <RaceSelector />
      <Panel title="Prediction inputs" kind="assumption" source="user inputs; circuit, constructor, grid and season features come from the database">
        <form className="form-row" onSubmit={(e) => { e.preventDefault(); if (ready) void run() }}>
          <Field label="Lap number" error={lapErr}><input aria-label="Lap number" inputMode="numeric" value={lap} onChange={(e) => setLap(e.target.value)} /></Field>
          <Field label="Tyre age (laps)" error={ageErr}><input aria-label="Tyre age" inputMode="numeric" value={age} onChange={(e) => setAge(e.target.value)} /></Field>
          <Field label="Tyre compound" hint="Optional; ignored unless the model was trained with compound data">
            <select aria-label="Tyre compound" value={compound} onChange={(e) => setCompound(e.target.value)}>
              <option value="">Not specified</option>
              {['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'].map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
          <button type="submit" className="primary" disabled={!ready || busy}>{busy ? 'Predicting…' : 'Predict lap time'}</button>
        </form>
        {!ready && !busy && sel.driver === '' && <p className="note">Select a season, Grand Prix and driver above.</p>}
      </Panel>

      {error && <ErrorBox error={error} />}
      {result && (
        <Panel title="Prediction result" kind="predicted" source={`active model v${result.model_version} (trained on database laps)`}>
          <div className="stats" data-testid="prediction-result">
            <Stat label="Predicted lap time" value={<span data-testid="predicted-time">{fmtLap(result.predicted_ms)}</span>} />
            <Stat label="80 % interval" value={`${fmtLap(result.interval_80_ms[0])} – ${fmtLap(result.interval_80_ms[1])}`} />
            <Stat label="Actual lap (ground truth)" value={result.actual_ms ? fmtLap(result.actual_ms) : 'n/a'}
              sub={result.actual_ms ? `error ${(result.error_ms! / 1000).toFixed(3)} s` : result.actual_note} />
          </div>
          <p className="note">{SPLIT_TEXT[result.split]} {result.unseen_circuit && ' ⚠ Circuit has no training history: absolute pace is unreliable.'}
            {!result.compound_used_by_model && compound && ' Compound was ignored: the model has no compound data.'}</p>
        </Panel>
      )}

      {sel.driver && (
        <Panel title="Predicted vs actual — all clean laps of this driver" kind="predicted" source="model predictions vs laps table">
          {pva.loading && <Spinner label="Computing predictions…" />}
          {pva.error && <ErrorBox error={pva.error} onRetry={pva.reload} />}
          {pva.data && !pva.data.available && <Empty title="No comparison available">{pva.data.reason}</Empty>}
          {pva.data?.available && (
            <>
              <div className="stats">
                <Stat label="MAE" value={`${(pva.data.mae_ms! / 1000).toFixed(3)} s`} sub={`${pva.data.n} laps`} />
                <Stat label="80 % interval coverage" value={`${(pva.data.interval_80_coverage! * 100).toFixed(0)} %`} />
                <Stat label="Data split" value={pva.data.split === 'held_out_test' ? 'held-out' : pva.data.split === 'training' ? 'training' : 'n/a'} />
              </div>
              <div className="chart" data-testid="pva-chart">
                <ResponsiveContainer width="100%" height={340}>
                  <ComposedChart data={pva.data.points.map((p) => ({ ...p, band: [p.p10, p.p90] }))}>
                    <CartesianGrid stroke="var(--grid)" />
                    <XAxis dataKey="lap_number" /><YAxis domain={['auto', 'auto']} tickFormatter={fmtLap} width={70} />
                    <Tooltip formatter={(v) => (Array.isArray(v) ? `${fmtLap(v[0])} – ${fmtLap(v[1])}` : fmtLap(Number(v)))} />
                    <Legend />
                    <Area dataKey="band" name="80% interval (predicted)" stroke="none" fill="#38bdf8" fillOpacity={0.2} isAnimationActive={false} />
                    <Line dataKey="p50" name="Predicted" stroke="#38bdf8" dot={false} strokeWidth={2} isAnimationActive={false} />
                    <Line dataKey="actual_ms" name="Actual" stroke="#e10600" dot={{ r: 2 }} strokeWidth={0} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </Panel>
      )}
    </div>
  )
}
