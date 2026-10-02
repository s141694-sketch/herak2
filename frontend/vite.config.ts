import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API lives on the Django backend; in development Vite proxies it so cookies stay same-origin.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: true,
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
  },
  preview: { port: 5173, strictPort: true, host: true },
})
