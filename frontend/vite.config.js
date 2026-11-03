import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the browser talks only to :5173 and /api is proxied to the backend, so session
// cookies stay same-origin (no SameSite/CORS problems). Production: see DEPLOYMENT.md
// (Vercel rewrites /api/* to the backend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_DEV_API_TARGET || 'http://localhost:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
