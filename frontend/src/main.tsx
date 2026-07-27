import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import './index.css';
import App from './App';
import { AuthProvider } from './auth/AuthProvider';

// One-time shim for the frank → frankly rename, so nobody loses their theme or
// gets dropped back into onboarding. Safe to delete once no old keys remain.
for (const [was, is] of [
  ['frank-theme', 'frankly-theme'],
  ['frank-onboarded', 'frankly-onboarded'],
]) {
  const old = localStorage.getItem(was);
  if (old !== null) {
    if (localStorage.getItem(is) === null) localStorage.setItem(is, old);
    localStorage.removeItem(was);
  }
}

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
