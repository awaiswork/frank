import { Navigate, Route, Routes } from 'react-router-dom';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { Layout } from './components/Layout';
import { Advisor } from './pages/Advisor';
import { Budgets } from './pages/Budgets';
import { Goals } from './pages/Goals';
import { Home } from './pages/Home';
import { Insight } from './pages/Insight';
import { Login } from './pages/Login';
import { Onboarding } from './pages/Onboarding';
import { Register } from './pages/Register';
import { Settings } from './pages/Settings';
import { Transactions } from './pages/Transactions';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/transactions" element={<Transactions />} />
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
