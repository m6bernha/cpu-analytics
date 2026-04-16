import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'

// Defaults tuned for the Render free-tier backend:
//   - retry: 3 -- cold-start + network hiccups are common.
//   - exponential backoff up to 30 s so a 50 s Render cold start has
//     time to finish before the third attempt.
//   - staleTime 5 min for low-churn data (filters, QT blocks, QT
//     standards). Individual tabs can override via `staleTime: Infinity`
//     where appropriate.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 30000),
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
