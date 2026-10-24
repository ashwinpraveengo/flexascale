import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into the Python package so the review startup never needs npm.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../src/flexascale/lab/static', emptyOutDir: true },
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8090' } },
})
