import type { Stint } from '../api'
import { COMPOUND_COLORS } from '../lib'

/** Horizontal strip showing stint lengths proportional to laps. */
export function StintBar({ stints, label }: { stints: Stint[]; label?: string }) {
  const total = stints.reduce((a, s) => a + s.laps, 0)
  return (
    <div className="stintbar" role="img" aria-label={label ?? stints.map((s) => `${s.compound} ${s.laps} laps`).join(', ')}>
      {stints.map((s, i) => (
        <div key={i} style={{ flex: s.laps / total, background: COMPOUND_COLORS[s.compound] ?? '#64748b' }}>
          <span>{s.compound[0]}{s.laps}</span>
        </div>
      ))}
    </div>
  )
}
