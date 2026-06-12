import { useState } from 'react';
import { Navigate, NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

type IconName = 'home' | 'advisor' | 'transactions' | 'budgets' | 'goals' | 'insight' | 'settings';

function Icon({ name }: { name: IconName }) {
  const p = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  switch (name) {
    case 'home':
      return (
        <svg {...p}>
          <path d="M3 10.5 12 3l9 7.5V21H3z" />
          <path d="M9 21v-7h6v7" />
        </svg>
      );
    case 'advisor':
      return (
        <svg {...p}>
          <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
          <path d="M12 8v3M12 14h.01" />
        </svg>
      );
    case 'transactions':
      return (
        <svg {...p}>
          <path d="M8 6h13M8 12h13M8 18h13" />
          <path d="M3 6h.01M3 12h.01M3 18h.01" />
        </svg>
      );
    case 'budgets':
      return (
        <svg {...p}>
          <path d="M3 3v18h18" />
          <rect x="7" y="11" width="3" height="6" />
          <rect x="13" y="7" width="3" height="10" />
        </svg>
      );
    case 'goals':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="5" />
          <circle cx="12" cy="12" r="1" />
        </svg>
      );
    case 'insight':
      return (
        <svg {...p}>
          <path d="M3 17l5-5 4 4 7-7" />
          <path d="M16 6h5v5" />
        </svg>
      );
    case 'settings':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H1a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 2.6 7a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H7a1.6 1.6 0 0 0 1-1.5V1a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V7a1.6 1.6 0 0 0 1.5 1H23a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" />
        </svg>
      );
  }
}

function useTheme(): ['dark' | 'light', () => void] {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (document.documentElement.getAttribute('data-theme') as 'dark' | 'light') || 'dark',
  );
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try {
      localStorage.setItem('frank-theme', next);
    } catch {
      /* ignore */
    }
    setTheme(next);
  };
  return [theme, toggle];
}

const PRIMARY: ReadonlyArray<readonly [string, string, IconName]> = [
  ['/', 'Home', 'home'],
  ['/advisor', 'Ask Frank', 'advisor'],
];
const RECORDS: ReadonlyArray<readonly [string, string, IconName]> = [
  ['/transactions', 'Transactions', 'transactions'],
  ['/budgets', 'Budgets', 'budgets'],
  ['/goals', 'Goals', 'goals'],
  ['/insights', 'Insight', 'insight'],
  ['/settings', 'Settings', 'settings'],
];

function NavItem({ to, label, icon }: { to: string; label: string; icon: IconName }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-[11px] px-3 py-2.5 text-[15px] font-semibold transition-colors ${
          isActive ? 'bg-surface text-ink' : 'text-muted hover:text-ink-2'
        }`
      }
    >
      <span className="grid h-[18px] w-[18px] place-items-center">
        <Icon name={icon} />
      </span>
      {label}
    </NavLink>
  );
}

export function Layout() {
  const { logout, user } = useAuth();
  const [theme, toggleTheme] = useTheme();

  // First-run users (no income yet) land in onboarding until they finish or skip.
  const needsOnboarding =
    user != null && user.monthly_income_cents == null && !localStorage.getItem('frank-onboarded');
  if (needsOnboarding) return <Navigate to="/onboarding" replace />;

  const today = new Date();
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysLeft = daysInMonth - today.getDate();
  const elapsed = (today.getDate() / daysInMonth) * 100;
  const monthName = today.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

  return (
    <div className="min-h-svh">
      <div className="mx-auto grid max-w-[1180px] grid-cols-[236px_1fr] items-start">
        {/* Sidebar */}
        <aside className="sticky top-0 flex h-svh flex-col gap-7 border-r border-line px-5 py-[26px]">
          <div className="flex items-center justify-between">
            <div className="flex items-baseline gap-px">
              <span className="font-display text-[25px] font-bold tracking-[-0.02em] text-ink">
                frank
              </span>
              <span className="font-display text-[25px] font-bold text-go">.</span>
            </div>
            <button
              onClick={toggleTheme}
              aria-label="Toggle light and dark"
              className="grid h-[38px] w-[38px] place-items-center rounded-[10px] border border-line bg-surface text-ink-2 hover:text-ink"
            >
              {theme === 'dark' ? (
                <svg
                  width="17"
                  height="17"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                </svg>
              ) : (
                <svg
                  width="17"
                  height="17"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
                </svg>
              )}
            </button>
          </div>

          <nav className="flex flex-col gap-[3px]">
            {PRIMARY.map(([to, label, icon]) => (
              <NavItem key={to} to={to} label={label} icon={icon} />
            ))}
            <div className="mx-1 my-2.5 h-px bg-line" />
            {RECORDS.map(([to, label, icon]) => (
              <NavItem key={to} to={to} label={label} icon={icon} />
            ))}
          </nav>

          <div className="mt-auto flex flex-col gap-2.5">
            <div className="rounded-[13px] border border-line bg-surface p-3.5">
              <div className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">
                This month
              </div>
              <div className="num mt-1.5 text-[15px] font-semibold text-ink">{monthName}</div>
              <div className="mt-2.5 flex items-center gap-2">
                <div className="relative h-[5px] flex-1 overflow-hidden rounded-full bg-inset">
                  <div
                    className="absolute inset-y-0 left-0 rounded-full bg-ink-2"
                    style={{ width: `${elapsed}%` }}
                  />
                </div>
                <span className="num text-[12px] text-muted">{daysLeft} left</span>
              </div>
            </div>
            <button
              onClick={logout}
              className="px-1.5 text-left text-[12.5px] font-semibold text-muted hover:text-ink"
            >
              Sign out
            </button>
          </div>
        </aside>

        {/* Main */}
        <main className="min-h-svh px-11 pt-10 pb-20">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
