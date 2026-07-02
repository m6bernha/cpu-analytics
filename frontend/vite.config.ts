import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split heavy, rarely-changing vendor libs into their own chunks so
        // they cache across app deploys. Rolldown (Vite 8) stopped hoisting
        // Recharts into a shared chunk automatically, which fused ~110 KB
        // gzip of charting into the entry bundle. Recharts and React only
        // change on a dependency bump, not on every app edit.
        manualChunks(id: string) {
          if (id.includes('node_modules/recharts/')) return 'recharts'
          if (
            id.includes('node_modules/react-dom/')
            || id.includes('node_modules/react/')
            || id.includes('node_modules/scheduler/')
          ) {
            return 'react'
          }
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**'],
  },
})
