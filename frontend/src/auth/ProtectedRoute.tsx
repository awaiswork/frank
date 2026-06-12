import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from './useAuth';

export function ProtectedRoute() {
  const { status } = useAuth();

  if (status === 'loading') {
    return (
      <div className="grid min-h-svh place-items-center text-muted">
        <span className="animate-pulse">Loading…</span>
      </div>
    );
  }
  if (status === 'anon') return <Navigate to="/login" replace />;
  return <Outlet />;
}
