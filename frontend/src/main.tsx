import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import './index.css';
import App from './App';
import { AuthProvider } from './auth/AuthProvider';

// Restore the saved theme before first paint (avoids a flash).
const savedTheme = localStorage.getItem('frank-theme');
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
