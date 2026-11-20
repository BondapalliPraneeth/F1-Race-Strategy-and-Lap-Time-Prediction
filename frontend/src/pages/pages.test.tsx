import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Predict from './Predict'
import { parsePlan } from './Simulate'

// Component tests stub the network boundary (fetch) only; response shapes mirror the real API schema.
function stubApi(routes: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const hit = Object.entries(routes).find(([k]) => url.includes(k))
    if (!hit) return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    return new Response(JSON.stringify(hit[1]), { status: 200 })
  }))
}
afterEach(() => vi.unstubAllGlobals())

const race = { id: 1, season: 2024, round: 1, name: 'Test GP', circuit: 'C', circuit_id: 'c', country: null, date: null, total_laps: 50,
  sessions: [{ key: 'race', label: 'Race', available: true }], data_availability: { laps: true, pit_stops: true, weather: false, tyre_compound: false },
  data_source: 'x', model_split: null, drivers: [{ driver_id: 'd0', code: 'D0', name: 'Driver Zero', constructor_id: 't', grid: 1, position: 1, status: 'Finished', laps: 50 }] }

describe('Predict page', () => {
  it('shows an explicit empty state when the database has no seasons', async () => {
    stubApi({ '/api/seasons': [] })
    render(<MemoryRouter initialEntries={['/predict']}><Predict /></MemoryRouter>)
    expect(await screen.findByText('No race data in the database')).toBeInTheDocument()
  })

  it('validates inputs and disables submit until a driver is chosen', async () => {
    stubApi({ '/api/seasons': [{ season: 2024, races: 1 }], '/api/races/1': race, '/api/races': { items: [race], total: 1 },
      '/predict-vs-actual': { available: false, reason: 'no model', points: [] } })
    render(<MemoryRouter initialEntries={['/predict?season=2024&race=1&driver=d0']}><Predict /></MemoryRouter>)
    const lap = await screen.findByLabelText('Lap number')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Predict lap time' })).toBeEnabled())
    await userEvent.clear(lap)
    await userEvent.type(lap, '99')
    expect(await screen.findByText(/between 1 and 50/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Predict lap time' })).toBeDisabled()
  })

  it('surfaces a backend error instead of fabricating a prediction', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/predict/laptime')) return new Response(JSON.stringify({ detail: 'No trained model is available' }), { status: 503 })
      if (url.includes('/seasons')) return new Response(JSON.stringify([{ season: 2024, races: 1 }]))
      if (url.includes('predict-vs-actual')) return new Response(JSON.stringify({ available: false, reason: 'no model', points: [] }))
      if (url.includes('/races/1')) return new Response(JSON.stringify(race))
      return new Response(JSON.stringify({ items: [race], total: 1 }))
    }))
    render(<MemoryRouter initialEntries={['/predict?season=2024&race=1&driver=d0']}><Predict /></MemoryRouter>)
    const btn = await screen.findByRole('button', { name: 'Predict lap time' })
    await waitFor(() => expect(btn).toBeEnabled())
    await userEvent.click(btn)
    expect(await screen.findByRole('alert')).toHaveTextContent('No trained model is available')
    expect(screen.queryByTestId('predicted-time')).not.toBeInTheDocument()
  })
})

describe('simulation plan parser', () => {
  const comps = ['SOFT', 'MEDIUM', 'HARD']
  it('parses a valid plan', () => {
    expect(parsePlan('medium:25, HARD:30', comps, 55).stints).toEqual([{ compound: 'MEDIUM', laps: 25 }, { compound: 'HARD', laps: 30 }])
  })
  it.each([['', /at least one/], ['MEDIUM:25', /add up to/], ['SLICK:55', /Unknown compound/], ['MEDIUM:x', /whole number/]])('rejects %j', (txt, msg) => {
    expect(parsePlan(txt, comps, 55).error).toMatch(msg)
  })
})
