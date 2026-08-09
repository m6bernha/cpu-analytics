import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Analytics } from '@vercel/analytics/react'
import './index.css'
import App from './App.tsx'
import { redirectLegacyLifterUrl } from './lib/route'

// Canonicalize legacy `?tab=lookup&lifter=X` links to `/athlete/X` BEFORE
// the first render. Doing it in an effect instead would be too late: the
// route hook reads location during mount and registers its listener in a
// passive effect, so a redirect fired from a layout effect dispatches to
// nobody and the app renders the wrong view.
redirectLegacyLifterUrl()

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
      {/* Vercel Web Analytics. Cookieless and no consent banner needed, so it
          mounts unconditionally. Automatic pageviews cover the real paths
          (/athlete/*, /meet/*); the tab stack lives in the query string, so
          tab usage is reported explicitly from App.tsx instead. Inert until
          Web Analytics is enabled on the Vercel project. */}
      <Analytics />
    </QueryClientProvider>
  </StrictMode>,
)
