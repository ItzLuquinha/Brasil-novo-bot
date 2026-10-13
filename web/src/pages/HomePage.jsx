import { useAuth } from '../auth/useAuth';
import { useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { apiRequest, getApiErrorMessage } from '../api/client';
import Sidebar from '../components/Sidebar';
import Navbar from '../components/Navbar';
import { ArrowUpRight, RotateCw, Server, LogIn, ShieldCheck } from 'lucide-react';

function AuthenticatedHome({ user }) {
  const navigate = useNavigate();
  const [guilds, setGuilds] = useState(null);
  const [loadingGuilds, setLoadingGuilds] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoadingGuilds(true);
        setError(null);
        return apiRequest('/guilds', { signal: controller.signal });
      })
      .then((data) => {
        if (!controller.signal.aborted && data !== null) setGuilds(Array.isArray(data) ? data : []);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingGuilds(false);
      });
    return () => controller.abort();
  }, [retryCount]);

  return (
    <div className="dashboard-shell">
      <Sidebar currentTab="overview" guild={null} setCurrentTab={() => navigate('/servers')} />
      <div className="dashboard-main">
        <Navbar currentTab="overview" />
        <main className="dashboard-content">
          <header className="dashboard-page-heading mb-5">
            <div>
              <h1 className="text-2xl font-semibold text-white">Bem-vindo, {user?.username || 'usuário'}</h1>
              <p className="mt-1 text-sm text-bn-muted">Visão geral dos servidores disponíveis para sua conta.</p>
            </div>
          </header>

          <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <article className="dashboard-metric-card rounded-lg border border-bn-border bg-bn-card p-4">
              <div className="flex items-center gap-2.5"><span className="dashboard-metric-icon"><Server size={16} /></span><p className="text-xs text-bn-muted">Servidores disponíveis</p></div>
              <p className="mt-3 text-2xl font-semibold leading-none text-white">{loadingGuilds ? '-' : error ? '-' : (guilds?.length ?? 0).toLocaleString('pt-BR')}</p>
            </article>
          </div>

          <section className="rounded-lg border border-bn-border bg-bn-card">
            <div className="flex items-center justify-between gap-3 border-b border-bn-border px-4 py-3">
              <div><h2 className="text-sm font-medium text-white">Servidores</h2><p className="mt-1 text-xs text-bn-muted">Abra o painel de um servidor que sua conta pode gerenciar.</p></div>
              <button type="button" onClick={() => navigate('/servers')} className="rounded-md border border-bn-border px-3 py-2 text-xs text-bn-muted">Ver todos</button>
            </div>
            {loadingGuilds && <p role="status" className="p-5 text-sm text-bn-muted">Carregando servidores…</p>}
            {!loadingGuilds && error && <div className="p-5"><p role="alert" className="text-sm text-red-200">{error}</p><button type="button" onClick={() => setRetryCount((value) => value + 1)} className="mt-3 inline-flex items-center gap-2 rounded-md bg-bn-green px-3 py-2 text-xs font-medium text-white"><RotateCw size={14} /> Tentar novamente</button></div>}
            {!loadingGuilds && !error && guilds?.length === 0 && <p className="p-5 text-sm text-bn-muted">Nenhum servidor ativo disponível para sua conta. Confira se o bot está presente e se você tem permissão para gerenciá-lo.</p>}
            {!loadingGuilds && !error && guilds?.length > 0 && <div className="divide-y divide-bn-border">{guilds.slice(0, 6).map((guild) => <button key={guild.id} type="button" onClick={() => navigate(`/dashboard/${encodeURIComponent(guild.id)}`)} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-[#101720]"><span className="flex min-w-0 items-center gap-3">{guild.icon_url ? <img src={guild.icon_url} alt="" className="h-8 w-8 rounded-full border border-bn-border object-cover" /> : <span className="flex h-8 w-8 items-center justify-center rounded-full border border-bn-border bg-[#121a23] text-bn-muted"><Server size={16} /></span>}<span className="min-w-0"><span className="block truncate text-sm font-medium text-white">{guild.name}</span><span className="mt-1 block text-[10px] text-bn-muted">ID: {guild.id}</span></span></span><ArrowUpRight size={16} className="shrink-0 text-bn-muted" /></button>)}</div>}
          </section>
        </main>
      </div>
    </div>
  );
}

export default function HomePage() {
  const { user, isAuthenticated, loading, login, authError, retryAuthentication } = useAuth();

  if (!loading && isAuthenticated) return <AuthenticatedHome user={user} />;

  return (
    <div className="dashboard-shell">
      <Sidebar currentTab="overview" guild={null} setCurrentTab={() => {}} />
      <div className="dashboard-main">
        <Navbar currentTab="overview" />
        <main className="dashboard-content">
          <header className="dashboard-page-heading mb-5">
            <div>
              <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
              <p className="mt-1 text-sm text-bn-muted">Visão geral e acesso às ferramentas do BN Bot.</p>
            </div>
            <span className="guest-auth-status"><span aria-hidden="true" />{loading ? 'Verificando sessão' : 'Login necessário'}</span>
          </header>

          {authError && !loading && (
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/25 bg-bn-card p-4">
              <p role="alert" className="text-sm text-amber-100">{authError}</p>
              <button type="button" onClick={retryAuthentication} className="rounded-md border border-bn-border px-3 py-2 text-xs text-white">Tentar novamente</button>
            </div>
          )}

          <div className="guest-dashboard-grid">
            <section className="guest-dashboard-card guest-login-panel">
              <div className="guest-panel-heading">
                <span className="guest-panel-icon"><ShieldCheck size={18} /></span>
                <div>
                  <h2>Entre no dashboard</h2>
                  <p>Autenticação segura com sua conta Discord.</p>
                </div>
              </div>
              <p className="guest-panel-copy">Conecte sua conta para carregar os servidores que você pode gerenciar e acessar as configurações reais do bot.</p>
              <button type="button" onClick={login} disabled={loading} className="guest-login-button">
                <LogIn size={15} />
                {loading ? 'Verificando sessão…' : 'Entrar com Discord'}
              </button>
            </section>

            <section className="guest-dashboard-card guest-session-panel">
              <h2>Estado da sessão</h2>
              <div className="guest-session-row"><span className="guest-session-dot" /><strong>{loading ? 'Verificando' : 'Não conectado'}</strong></div>
              <p>As informações de servidores e as ferramentas de administração aparecem depois que o Discord confirmar sua identidade e permissões.</p>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
