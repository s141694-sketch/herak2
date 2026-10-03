import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API lives on the Django backend; in development Vite proxies it so cookies stay same-origin.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'
// The collaboration service, reached at /collab as nginx does in production.
const collabTarget = process.env.VITE_COLLAB_PROXY ?? 'ws://127.0.0.1:1234'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: true,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/collab': { target: collabTarget, ws: true, rewrite: (path) => path.replace(/^\/collab/, '') || '/' },
    },
  },
  preview: { port: 5173, strictPort: true, host: true },
})
