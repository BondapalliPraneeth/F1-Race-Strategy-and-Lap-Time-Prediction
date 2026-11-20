/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': backend } },
  preview: { port: 5173, proxy: { '/api': backend } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], globals: true, exclude: ['e2e/**', 'node_modules/**'] },
})
