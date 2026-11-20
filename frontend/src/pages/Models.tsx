import { api } from '../api'
import { Empty, ErrorBox, Panel, Spinner, Stat } from '../components/ui'
import { useAsync } from '../lib'

const s = (ms: unknown) => (typeof ms === 'number' ? `${(ms / 1000).toFixed(3)} s` : '—')
const pct = (v: unknown) => (typeof v === 'number' ? `${(v * 100).toFixed(0)} %` : '—')

export default function Models() {
  const m = useAsync(() => api.models(), [])
  const h = useAsync(() => api.health(), [])
  const active = m.data?.find((x) => x.is_active)
  const met = active?.metrics ?? {}
  return (
    <div className="page">
      <h1>Model &amp; Data</h1>
      <p className="lede">What the active model was trained on, how it was validated, and what the data source does not provide.</p>
      {m.loading && <Spinner />}
      {m.error && <ErrorBox error={m.error} onRetry={m.reload} />}
      {m.data && !active && <Empty title="No trained model">Run <code>python -m app.cli train</code> after ingesting data.</Empty>}
      {active && (
        <>
          <Panel title={`Active model v${active.id}`} kind="actual" source="model registry (model_versions table), computed on held-out races">
            <div className="stats">
              <Stat label="Held-out MAE (seen circuits)" value={s(met.mae_ms)} sub={`baseline ${s(met.baseline_circuit_median_mae_ms)}`} />
              <Stat label="80 % interval coverage" value={pct(met.interval_80_coverage)} sub="nominal 80 %" />
              <Stat label="Train / test races" value={`${active.n_train_races} / ${active.n_test_races}`} sub="chronological split" />
              <Stat label="Seed" value={active.random_seed} sub={`data ${active.data_fingerprint.slice(0, 10)}`} />
            </div>
            <details><summary>Feature specification</summary>
              <p>Target: <code>{active.feature_spec.target}</code></p>
              <p>Numeric: {active.feature_spec.numeric.join(', ')} · Categorical: {active.feature_spec.categorical.join(', ')}</p>
              <p>{active.feature_spec.cleaning}</p></details>
            <details><summary>All stored metrics (JSON)</summary><pre>{JSON.stringify(met, null, 2)}</pre></details>
          </Panel>
          {m.data!.length > 1 && <Panel title="Model history" kind="actual" source="model registry">
            <table><thead><tr><th>Version</th><th>Created</th><th>MAE</th><th>Active</th></tr></thead>
              <tbody>{m.data!.map((x) => <tr key={x.id}><td>v{x.id}</td><td>{x.created_at?.slice(0, 19)}</td><td>{s(x.metrics?.mae_ms)}</td><td>{x.is_active ? 'yes' : ''}</td></tr>)}</tbody></table></Panel>}
        </>
      )}
      <Panel title="Data availability &amp; limitations" kind="actual" source="Jolpica-F1 (Ergast-compatible) historical API">
        <ul className="explain">
          <li>Available: race results, per-lap times, pit stops, grid and finishing positions.</li>
          <li>Not available from the source: tyre compound, weather, qualifying/practice laps. The model therefore does not use compound; compound profiles in the optimizer are labelled assumptions.</li>
          <li>Tyre age is laps since the driver’s last stop — a lower bound, since used tyres cannot be detected.</li>
        </ul>
        {h.data && <p className="note">Races with lap data in database: <strong>{h.data.races_with_laps}</strong></p>}
      </Panel>
    </div>
  )
}
