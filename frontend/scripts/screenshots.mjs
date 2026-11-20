// Captures real screenshots of the running app (real API + real database). Usage: node scripts/screenshots.mjs
import { chromium } from '@playwright/test'
const base = process.env.APP_URL ?? 'http://127.0.0.1:5173'
const out = '../docs/screenshots'
const q = 'season=2024&race=22&driver=leclerc'
const b = await chromium.launch()
const page = await b.newPage({ viewport: { width: 1360, height: 900 } })
const shot = async (n) => { await page.waitForTimeout(800); await page.screenshot({ path: `${out}/${n}.png`, fullPage: true }) }

await page.goto(`${base}/analysis?${q}`)
await page.getByRole('checkbox').first().click()
await page.getByRole('region', { name: 'Lap times' }).waitFor()
await shot('01-analysis')

await page.goto(`${base}/predict?${q}`)
await page.getByRole('button', { name: 'Predict lap time' }).click()
await page.getByTestId('predicted-time').waitFor()
await page.getByTestId('pva-chart').waitFor()
await shot('02-predict')

await page.goto(`${base}/degradation?${q}`)
await page.getByTestId('deg-chart').waitFor()
await shot('03-degradation')

await page.goto(`${base}/optimize?${q}`)
await page.getByRole('button', { name: 'Find optimal strategy' }).click()
await page.getByTestId('pit-windows').waitFor()
await shot('04-optimize')

await page.goto(`${base}/simulate?${q}`)
await page.getByRole('textbox', { name: 'Strategy 1' }).fill('MEDIUM:25, HARD:25')
await page.getByRole('textbox', { name: 'Strategy 2' }).fill('SOFT:15, HARD:35')
await page.getByLabel('Simulations').fill('2000')
await page.getByRole('button', { name: 'Run simulation' }).click()
await page.getByTestId('sim-table').waitFor()
await shot('05-simulate')

await page.goto(`${base}/models`)
await shot('06-models')
await b.close()
