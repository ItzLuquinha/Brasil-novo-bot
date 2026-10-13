import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, RotateCw, Search, Server } from 'lucide-react';
import Navbar from '../components/Navbar';
import { apiRequest, getApiErrorMessage } from '../api/client';

export default function ServerSelectPage() {
  const [guilds, setGuilds] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [search, setSearch] = useState('');
  const navigate = useNavigate();
  const retry = useCallback(() => setRetryCount((current) => current + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoading(true);
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
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [retryCount]);

  const filteredGuilds = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('pt-BR');
    if (!query) return guilds || [];
    return (guilds || []).filter((guild) => `${guild.name || ''} ${guild.id || ''}`.toLocaleLowerCase('pt-BR').includes(query));
  }, [guilds, search]);

  return (
    <div className="flex min-h-screen flex-col bg-bn-dark">
      <Navbar currentTab="servers" showAccount />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-5 md:px-6 md:py-6">
        <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
          <div>
            <h1 className="text-2xl font-semibold text-white">Servidores</h1>
            <p className="mt-1 text-sm text-bn-muted">Escolha um servidor para o qual sua conta possui permissão de gerenciamento.</p>
          </div>
          <label className="relative block w-full sm:max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-bn-muted" aria-hidden="true" />
            <input className="server-search" type="search" aria-label="Pesquisar servidores" placeholder="Pesquisar servidores..." value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
        </div>

        {loading && <p role="status" className="rounded-lg border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando servidores…</p>}
        {!loading && error && <div className="rounded-lg border border-red-500/30 bg-bn-card p-6"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-4 inline-flex items-center gap-2 rounded-md bg-bn-green px-4 py-2 text-sm font-semibold text-bn-dark"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
        {!loading && !error && guilds?.length === 0 && <div className="rounded-lg border border-bn-border bg-bn-card p-8 text-sm text-bn-muted">Nenhum servidor ativo disponível para sua conta. Confira se o bot está presente e se você tem permissão para gerenciá-lo.</div>}
        {!loading && !error && guilds?.length > 0 && filteredGuilds.length === 0 && <div className="rounded-lg border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Nenhum servidor corresponde à pesquisa.</div>}
        {!loading && !error && filteredGuilds.length > 0 && (
          <section className="server-directory overflow-hidden rounded-lg border border-bn-border bg-bn-card" aria-label="Servidores disponíveis">
            <div className="server-directory-head grid grid-cols-[minmax(0,1fr)_100px_24px] items-center gap-3 border-b border-bn-border px-4 py-2 text-[10px] font-medium uppercase tracking-wide text-bn-muted sm:grid-cols-[minmax(0,1fr)_140px_24px]">
              <span>Servidor</span><span className="hidden sm:block">Status</span><span />
            </div>
            <div>
              {filteredGuilds.map((guild) => (
                <button
                  type="button"
                  key={guild.id}
                  onClick={() => navigate(`/dashboard/${encodeURIComponent(guild.id)}`)}
                  className="server-picker-card flex w-full items-center justify-between gap-3 border-0 border-b border-bn-border px-4 py-3 text-left last:border-b-0"
                >
                  <span className="flex min-w-0 items-center gap-3">
                    {guild.icon_url ? <img src={guild.icon_url} alt="" className="h-9 w-9 rounded-full border border-bn-border object-cover" /> : <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-bn-border bg-[#121a23] text-bn-muted"><Server size={17} /></span>}
                    <span className="min-w-0"><span className="block truncate text-sm font-medium text-white">{guild.name}</span><span className="mt-1 block truncate text-[10px] text-bn-muted">ID: {guild.id}</span></span>
                  </span>
                  <span className="hidden items-center gap-2 text-[11px] text-bn-muted sm:flex"><span className={`h-1.5 w-1.5 rounded-full ${guild.active ? 'bg-emerald-400' : 'bg-slate-500'}`} />{guild.active ? 'Ativo' : 'Inativo'}</span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-bn-muted" />
                </button>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
