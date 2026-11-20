import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAsync } from './lib'
import Analysis from './pages/Analysis'
import Degradation from './pages/Degradation'
import Models from './pages/Models'
import Optimize from './pages/Optimize'
import Predict from './pages/Predict'
import Simulate from './pages/Simulate'

const NAV = [
  { to: '/analysis', label: 'Race Analysis' },
  { to: '/predict', label: 'Lap-Time Prediction' },
  { to: '/degradation', label: 'Tyre Degradation' },
  { to: '/optimize', label: 'Strategy Optimizer' },
  { to: '/simulate', label: 'What-If Simulation' },
  { to: '/models', label: 'Model & Data' },
]

export default function App() {
  const { search } = useLocation()
  const health = useAsync(() => api.health(), [])
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="stripe" />PIT WALL<small>Strategy &amp; Lap-Time Lab</small></div>
        <nav aria-label="Main">
          {NAV.map((n) => <NavLink key={n.to} to={{ pathname: n.to, search }}>{n.label}</NavLink>)}
        </nav>
        <div className="status" data-testid="api-status">
          {health.loading && 'Connecting to API…'}
          {health.error && <span className="bad">API offline</span>}
          {health.data && (
            <>
              <span className="good">API online</span>
              <small>{health.data.races_with_laps} races · model {health.data.active_model ? `v${health.data.active_model}` : 'none'}</small>
            </>
          )}
        </div>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/analysis" replace />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/predict" element={<Predict />} />
          <Route path="/degradation" element={<Degradation />} />
          <Route path="/optimize" element={<Optimize />} />
          <Route path="/simulate" element={<Simulate />} />
          <Route path="/models" element={<Models />} />
          <Route path="*" element={<Navigate to="/analysis" replace />} />
        </Routes>
      </main>
    </div>
  )
}
