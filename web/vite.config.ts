import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Default proxy target matches docker-compose (API exposed on :8081)
const target = process.env.VITE_API_TARGET ?? 'http://localhost:8081'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/docs': { target, changeOrigin: true },
      '/openapi.json': { target, changeOrigin: true },
      '/redoc': { target, changeOrigin: true },
      '/healthz': { target, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/react-dom/') || id.includes('/react/')) return 'vendor-react'
          if (id.includes('/@tanstack/')) return 'vendor-tanstack'
          return undefined
        },
      },
    },
  },
})
