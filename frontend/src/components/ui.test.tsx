import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import { initialForm, toParams, validate } from './ParamsForm'
import { StintBar } from './StintBar'
import { Badge, Empty, ErrorBox, Panel } from './ui'

describe('data-kind labelling', () => {
  it.each([['actual', 'ACTUAL'], ['predicted', 'PREDICTED'], ['simulated', 'SIMULATED'], ['assumption', 'ASSUMPTION']] as const)(
    'Badge %s shows %s', (kind, text) => {
      render(<Badge kind={kind} />)
      expect(screen.getByText(text)).toBeInTheDocument()
    })

  it('Panel shows its data kind and source', () => {
    render(<Panel title="Lap times" kind="predicted" source="trained model v3"><p>body</p></Panel>)
    expect(screen.getByRole('region', { name: 'Lap times' })).toBeInTheDocument()
    expect(screen.getByTestId('badge-predicted')).toBeInTheDocument()
    expect(screen.getByText(/Source: trained model v3/)).toBeInTheDocument()
  })
})

describe('states', () => {
  it('ErrorBox announces the error and offers retry', () => {
    render(<ErrorBox error={new ApiError(503, 'No trained model')} onRetry={() => undefined} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Error 503')
    expect(screen.getByRole('alert')).toHaveTextContent('No trained model')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
  it('ErrorBox distinguishes connection failures', () => {
    render(<ErrorBox error={new ApiError(0, 'Cannot reach the backend API.')} />)
    expect(screen.getByText('Connection problem')).toBeInTheDocument()
  })
  it('Empty explains why there is nothing to show', () => {
    render(<Empty title="No weather data">source does not publish weather</Empty>)
    expect(screen.getByTestId('empty-state')).toHaveTextContent('source does not publish weather')
  })
})

describe('strategy parameter form validation', () => {
  it('defaults are valid and convert to API params (pit loss omitted = data-derived)', () => {
    const f = initialForm()
    expect(validate(f)).toEqual({})
    const p = toParams(f)
    expect(p.pit_loss_ms).toBeUndefined()
    expect(p.min_compounds_used).toBe(2)
  })
  it('converts seconds to milliseconds and flags out-of-range values', () => {
    const f = { ...initialForm(), pitLoss: '21.5' }
    expect(toParams(f).pit_loss_ms).toBe(21500)
    expect(validate({ ...f, pitLoss: '2' }).pitLoss).toMatch(/5–60/)
    expect(validate({ ...f, maxStops: '9' }).maxStops).toBeDefined()
    expect(validate({ ...f, minCompounds: '4' }).minCompounds).toBeDefined()
    const bad = initialForm(); bad.compounds.SOFT.max_stint_laps = 2
    expect(validate(bad)['SOFT.max']).toBeDefined()
  })
})

describe('StintBar', () => {
  it('has an accessible description of the plan', () => {
    render(<StintBar stints={[{ compound: 'MEDIUM', laps: 25 }, { compound: 'HARD', laps: 30 }]} />)
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', 'MEDIUM 25 laps, HARD 30 laps')
  })
})
