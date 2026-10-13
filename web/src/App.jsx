import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './auth/useAuth';
import HomePage from './pages/HomePage';
import ServerSelectPage from './pages/ServerSelectPage';
import GuildDashboard from './pages/dashboard/GuildDashboard';

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading, authError, retryAuthentication } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen bg-bn-dark flex items-center justify-center text-bn-muted text-sm">
        Carregando sessão...
      </div>
    );
  }
  if (authError) {
    return <div className="flex min-h-screen items-center justify-center bg-bn-dark p-6"><div className="max-w-lg rounded-2xl border border-bn-border bg-bn-card p-8"><h1 className="text-lg font-bold text-white">Não foi possível validar sua sessão</h1><p role="alert" className="mt-3 text-sm text-bn-muted">{authError}</p><button onClick={retryAuthentication} className="mt-5 rounded-xl bg-bn-green px-4 py-2 text-sm font-semibold text-bn-dark">Tentar novamente</button></div></div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>

        <Route path="/" element={<HomePage />} />


        <Route
          path="/servers"
          element={
            <ProtectedRoute>
              <ServerSelectPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/dashboard/:guildId"
          element={
            <ProtectedRoute>
              <GuildDashboard />
            </ProtectedRoute>
          }
        />


        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}