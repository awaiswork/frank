import { Navigate, Route, Routes } from 'react-router-dom';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { Layout } from './components/Layout';
import { Advisor } from './pages/Advisor';
import { AuthCallback } from './pages/AuthCallback';
import { Budgets } from './pages/Budgets';
import { ForgotPassword } from './pages/ForgotPassword';
import { Goals } from './pages/Goals';
import { Home } from './pages/Home';
import { Insight } from './pages/Insight';
import { Login } from './pages/Login';
import { Onboarding } from './pages/Onboarding';
import { Register } from './pages/Register';
import { ResetPassword } from './pages/ResetPassword';
import { Settings } from './pages/Settings';
import { Transactions } from './pages/Transactions';
import { Lending } from './pages/Lending';
import { Recurring } from './pages/Recurring';
import { Wealth } from './pages/Wealth';
import { VerifyCode } from './pages/VerifyCode';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      {/* Codes, not links: nothing here is reachable from an inbox, so these
          carry their state in the router rather than the URL. */}
      <Route path="/verify" element={<VerifyCode />} />
      {/* Where Google's redirect lands. The refresh cookie is already set. */}
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/wealth" element={<Wealth />} />
          <Route path="/lending" element={<Lending />} />
          <Route path="/recurring" element={<Recurring />} />
          <Route path="/budgets" element={<Budgets />} />
          <Route path="/goals" element={<Goals />} />
          <Route path="/advisor" element={<Advisor />} />
          <Route path="/insights" element={<Insight />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
