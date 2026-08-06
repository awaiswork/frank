import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import './index.css';
import App from './App';
import { AuthProvider } from './auth/AuthProvider';

// One-time shim for the frank → frankly rename, so nobody loses their theme.
// Safe to delete once no old keys remain.
const legacyTheme = localStorage.getItem('frank-theme');
if (legacyTheme !== null) {
  if (localStorage.getItem('frankly-theme') === null) {
    localStorage.setItem('frankly-theme', legacyTheme);
  }
  localStorage.removeItem('frank-theme');
}

// The onboarding flag is per-account now (`lib/onboarding`). The old global
// keys are not migrated — carrying them over is exactly what made a second
// account on this browser skip setup it had never seen. Cleared so they don't
// sit around looking meaningful.
localStorage.removeItem('frank-onboarded');
localStorage.removeItem('frankly-onboarded');

// Restore the saved theme before first paint (avoids a flash).
const savedTheme = localStorage.getItem('frankly-theme');
if (savedTheme === 'light' || savedTheme === 'dark') {
  document.documentElement.setAttribute('data-theme', savedTheme);
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
