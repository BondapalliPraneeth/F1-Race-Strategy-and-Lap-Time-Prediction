/** Typed client for the backend API. All data shown in the UI comes through here (no mocks). */

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail))
    return detail.map((d) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('; ')
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; issues?: Record<string, string[]> }
    if (d.issues) return `${d.message}: ${Object.entries(d.issues).map(([k, v]) => `${k} — ${v.join(', ')}`).join(' | ')}`
    return d.message ?? JSON.stringify(detail)
  }
  return 'Request failed'
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  } catch {
    throw new ApiError(0, 'Cannot reach the backend API. Is the server running?')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, describe(body?.detail ?? body?.error))
  return body as T
}

const qs = (p: Record<string, string | number | undefined | string[]>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(p)) {
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x))
    else if (v !== undefined && v !== '') u.set(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

export interface Race {
  id: number; season: number; round: number; name: string; circuit: string; circuit_id: string
  country: string | null; date: string | null; total_laps: number
  sessions: { key: string; label: string; available: boolean }[]
}
export interface DriverEntry {
  driver_id: string; code: string | null; name: string; constructor_id: string | null
  grid: number | null; position: number | null; status: string | null; laps: number
}
export interface RaceDetail extends Race {
  data_availability: { laps: boolean; pit_stops: boolean; weather: boolean; tyre_compound: boolean }
  data_source: string; model_split: string | null; drivers: DriverEntry[]
}
export interface Lap {
  driver_id: string; lap_number: number; position: number | null; lap_time_ms: number | null
  stint_number: number; tyre_age: number; is_in_lap: boolean; is_out_lap: boolean
  is_neutralised: boolean; compound: string | null
}
export interface CompareDriver {
  driver_id: string; laps: Lap[]; median_clean_lap_ms: number | null; n_clean_laps: number
  stints: { stint_number: number; start_lap: number; end_lap: number; compound: string | null }[]
}
export interface Prediction {
  predicted_ms: number; interval_80_ms: [number, number]; model_version: number; split: string
  compound_used_by_model: boolean; actual_ms: number | null; error_ms: number | null
  actual_note: string | null; unseen_circuit: boolean
}
export interface PvaPoint { lap_number: number; tyre_age: number; actual_ms: number; p10: number; p50: number; p90: number }
export interface Pva {
  available: boolean; reason?: string; model_version?: number; split?: string; mae_ms?: number
  interval_80_coverage?: number; n?: number; points: PvaPoint[]
}
export interface StintDeg {
  stint_number: number; start_lap: number; end_lap: number; compound: string | null; n_clean_laps: number
  slope_ms_per_lap: number | null; slope_se: number | null; intercept_ms: number | null
  uncertain: boolean; uncertainty_reason: string | null
  points: { tyre_age: number; lap_number: number; lap_time_ms: number; fuel_corrected_ms: number }[]
}
export interface Degradation {
  available: boolean; reason?: string; fuel_slope_ms_per_lap: number | null; pooled_degradation_ms_per_lap?: number
  pooled_degradation_se?: number; stints: StintDeg[]; notes?: string[]
  model_curve?: { available?: boolean; reason?: string; at_lap?: number; model_version?: number; points?: { tyre_age: number; predicted_ms: number }[] }
}
export interface Stint { compound: string; laps: number }
export interface PitWindow { stop: number; optimal_lap: number; earliest: number; latest: number }
export interface RankedStrategy { label: string; stints: Stint[]; pit_laps: number[]; predicted_total_ms: number; pit_windows: PitWindow[] }
export interface CompoundProfile { offset_ms: number; degradation_multiplier: number; max_stint_laps: number }
export interface StrategyParams {
  pit_loss_ms?: number; max_stops?: number; min_compounds_used?: number; min_stint_laps?: number
  compounds?: Record<string, CompoundProfile>; traffic_penalty_ms?: number; traffic_laps?: number
  inlap_penalty_ms?: number; outlap_penalty_ms?: number
}
export interface OptimizeResult {
  model_version: number; split: string; recommended: RankedStrategy; alternatives: RankedStrategy[]
  explanation: string[]; assumption_notes: string[]; compute_seconds: number
  pit_loss_estimate: { pit_loss_ms: number; std_ms: number; n_stops: number; scope: string; method: string }
  pit_loss_overridden: boolean; config: { compounds: Record<string, CompoundProfile>; total_laps: number; pit_loss_ms: number }
  actual_strategy: { pit_laps: number[]; stint_lengths: number[]; completed_full_distance: boolean; actual_total_ms: number | null }
}
export interface SimStrategy {
  label: string; stints: Stint[]; pit_laps: number[]; mean_ms: number; median_ms: number; std_ms: number
  p5_ms: number; p25_ms: number; p75_ms: number; p95_ms: number; win_probability: number; deterministic_ms: number
  histogram: { edges_ms: number[]; counts: number[] }
}
export interface SimResult {
  n_sims: number; seed: number; sc_hit_rate: number; compute_seconds: number; strategies: SimStrategy[]
  scenario: { safety_car: SafetyCar; weather: { start_lap: number; end_lap: number; slowdown_pct: number }[]; hypothetical: boolean }
}
export interface SafetyCar { mode: 'none' | 'random' | 'fixed'; probability: number; start_lap?: number; duration_laps: number; vsc: boolean }
export interface ModelInfo {
  id: number; created_at: string | null; is_active: boolean; n_train_races: number; n_test_races: number
  test_races: number[]; data_fingerprint: string; random_seed: number
  feature_spec: { version: string; numeric: string[]; categorical: string[]; target: string; cleaning: string }
  metrics: Record<string, any>
}

export interface StrategyContext {
  compound_profile_source: 'data' | 'assumption'; model_uses_compound: boolean
  compound_profiles: Record<string, CompoundProfile>
  compound_evidence: Record<string, { scope: string; n_stints: number; median_stint_laps: number; p90_stint_laps: number; longest_stint_laps: number }>
  safety_car: { available: boolean; reason?: string; scope?: string; n_races?: number; sc_probability?: number; vsc_probability?: number
    sc_mean_laps_per_period?: number | null; vsc_mean_laps_per_period?: number | null; source?: string }
  weather: { available: boolean; reason?: string; source?: string; n_laps?: number; rain_lap_share?: number; humidity_pct_mean?: number | null
    air_temp_c?: { min: number; mean: number; max: number }; track_temp_c?: { min: number; mean: number; max: number } }
}

export const api = {
  strategyContext: (id: number) => request<StrategyContext>(`/api/races/${id}/strategy-context`),
  health: () => request<{ status: string; races_with_laps: number; active_model: number | null }>('/api/health'),
  seasons: () => request<{ season: number; races: number }[]>('/api/seasons'),
  races: (season?: number) => request<{ items: Race[]; total: number }>(`/api/races${qs({ season, page_size: 100 })}`),
  race: (id: number) => request<RaceDetail>(`/api/races/${id}`),
  compare: (id: number, drivers: string[]) => request<{ drivers: CompareDriver[]; source: string }>(`/api/races/${id}/compare${qs({ drivers })}`),
  pitStops: (id: number) => request<{ items: { driver_id: string; stop_number: number; lap: number; duration_ms: number | null }[] }>(`/api/races/${id}/pit-stops`),
  weather: (id: number) => request<{ available: boolean; reason: string | null; items: { lap_number: number; air_temp_c: number; track_temp_c: number }[] }>(`/api/races/${id}/weather`),
  predict: (b: { race_id: number; driver_id: string; lap_number: number; tyre_age: number; compound?: string }) =>
    request<Prediction>('/api/predict/laptime', { method: 'POST', body: JSON.stringify(b) }),
  pva: (id: number, driver: string) => request<Pva>(`/api/races/${id}/predict-vs-actual${qs({ driver_id: driver })}`),
  degradation: (id: number, driver: string) => request<Degradation>(`/api/races/${id}/degradation${qs({ driver_id: driver })}`),
  optimize: (b: { race_id: number; driver_id: string; params: StrategyParams }) =>
    request<OptimizeResult>('/api/strategy/optimize', { method: 'POST', body: JSON.stringify(b) }),
  simulate: (b: unknown) => request<SimResult>('/api/strategy/simulate', { method: 'POST', body: JSON.stringify(b) }),
  models: () => request<ModelInfo[]>('/api/models'),
}
