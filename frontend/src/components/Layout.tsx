import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

const LINKS: ReadonlyArray<readonly [string, string]> = [
  ['/', 'Home'],
  ['/transactions', 'Transactions'],
  ['/budgets', 'Budgets'],
  ['/goals', 'Goals'],
];

export function Layout() {
  const { logout } = useAuth();

  return (
    <div className="min-h-svh">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3">
          <span className="font-display text-[22px] font-bold text-ink">Frank</span>
          <nav className="flex items-center gap-1">
            {LINKS.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    isActive ? 'bg-ink text-paper' : 'text-ink-2 hover:text-ink'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <button onClick={logout} className="text-[13px] text-muted hover:text-ink">
            Sign out
          </button>
        </div>
      </header>
      <main className="animate-fade-up mx-auto max-w-3xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
