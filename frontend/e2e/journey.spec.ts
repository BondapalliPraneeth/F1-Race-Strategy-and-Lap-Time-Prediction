import { expect, test, type Page } from '@playwright/test'

async function selectRace(page: Page, driver = true) {
  await page.getByLabel('Season').selectOption({ index: 1 })
  await page.getByLabel('Grand Prix').selectOption({ index: 1 })
  if (driver) await page.getByLabel('Driver').selectOption({ index: 1 })
}

test('full journey: select race -> data -> predict -> degradation -> optimize -> simulate', async ({ page }) => {
  await page.goto('/analysis')
  await expect(page.getByText('API online')).toBeVisible()
  await selectRace(page, false)
  await page.getByRole('checkbox').first().click()
  await expect(page.getByRole('checkbox').first()).toBeChecked()
  await expect(page.getByRole('region', { name: 'Lap times' })).toBeVisible()
  await expect(page.getByTestId('badge-actual').first()).toBeVisible()

  await page.getByRole('link', { name: /Prediction/ }).click()
  await page.getByLabel('Driver').selectOption({ index: 1 })
  await page.getByRole('button', { name: 'Predict lap time' }).click()
  await expect(page.getByTestId('predicted-time')).toContainText(':')
  await expect(page.getByText(/80 % interval/).first()).toBeVisible()
  await expect(page.getByTestId('pva-chart')).toBeVisible()

  await page.getByRole('link', { name: /Degradation/ }).click()
  await expect(page.getByTestId('deg-chart')).toBeVisible()

  await page.getByRole('link', { name: /Optimi/ }).click()
  await page.getByRole('button', { name: 'Find optimal strategy' }).click()
  await expect(page.getByTestId('recommended-label')).toBeVisible()
  await expect(page.getByTestId('explanation')).toBeVisible()
  await expect(page.getByTestId('pit-windows')).toBeVisible()

  await page.getByRole('link', { name: /Simulat/ }).click()
  await page.getByRole('textbox', { name: 'Strategy 1' }).fill('MEDIUM:20, HARD:20')
  await page.getByRole('textbox', { name: 'Strategy 2' }).fill('SOFT:10, HARD:30')
  await page.getByLabel('Simulations').fill('300')
  await page.getByRole('button', { name: 'Run simulation' }).click()
  await expect(page.getByTestId('sim-table')).toBeVisible()
  await expect(page.getByTestId('badge-simulated').first()).toBeVisible()
  await expect(page.getByText(/Win prob/).first()).toBeVisible()
})

test('prediction form validates input before calling the API', async ({ page }) => {
  await page.goto('/predict')
  await selectRace(page)
  await page.getByLabel('Lap number').fill('abc')
  await expect(page.getByRole('alert').first()).toContainText(/whole lap/)
  await expect(page.getByRole('button', { name: 'Predict lap time' })).toBeDisabled()
  await page.getByLabel('Lap number').fill('10')
  await page.getByLabel('Tyre age').fill('30')
  await expect(page.getByRole('alert').first()).toContainText(/cannot exceed/)
})

test('weather panel is an honest empty state, and an API outage shows an error', async ({ page }) => {
  await page.goto('/analysis')
  await selectRace(page, false)
  await expect(page.getByText(/weather/i).first()).toBeVisible()
  await page.route('**/api/races/*/degradation*', (r) => r.fulfill({ status: 503, json: { detail: 'model unavailable' } }))
  await page.goto('/degradation')
  await selectRace(page)
  await expect(page.getByRole('alert')).toContainText(/model unavailable/)
})

test('simulation rejects stints that do not add up to race distance', async ({ page }) => {
  await page.goto('/simulate')
  await selectRace(page)
  await page.getByRole('textbox', { name: 'Strategy 1' }).fill('MEDIUM:5, HARD:5')
  await expect(page.getByRole('alert').first()).toContainText(/add up to/)
  await expect(page.getByRole('button', { name: 'Run simulation' })).toBeDisabled()
})
