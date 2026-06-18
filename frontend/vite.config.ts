import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendPort = process.env.BACKEND_PORT ?? '8001'
const backendBase = `http://localhost:${backendPort}`

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backendBase,
      '/ws': { target: `ws://localhost:${backendPort}`, ws: true },
    },
  },
})
