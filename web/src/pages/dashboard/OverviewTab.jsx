import { useEffect, useState } from 'react';
import { AlertTriangle, Key, RotateCw, Shield, Users, MessageSquare, Coins, Ticket, Lightbulb, Activity } from 'lucide-react';
import { useAuth } from '../../auth/useAuth';
import { apiRequest, getApiErrorMessage } from '../../api/client';
import SuggestionsDialog from './SuggestionsDialog';

const QUICK_LINKS = [
  { title: 'Auto Moderação', desc: 'Configure regras contra spam, convites e excesso de menções.', action: 'Configurar AutoMod', tab: 'automod', icon: Shield },
  { title: 'Casos de moderação', desc: 'Consulte as ações de moderação registradas no servidor.', action: 'Ver casos', tab: 'moderation', icon: AlertTriangle },
  { title: 'Configurações gerais', desc: 'Ajuste idioma, fuso horário e recursos disponíveis.', action: 'Abrir configurações', tab: 'settings', icon: Key },
  { title: 'Economia do servidor', desc: 'Consulte os saldos que estão persistidos no banco.', action: 'Ver economia', tab: 'economy', icon: Coins },
  { title: 'Membros e níveis', desc: 'Consulte membros ativos e seus dados de experiência.', action: 'Ver membros', tab: 'members', icon: Users },
  { title: 'Estatísticas e atividade', desc: 'Analise tendências, canais ativos, contadores e cargos automáticos.', action: 'Ver estatísticas', tab: 'statistics', icon: Activity },
  { title: 'Logs de auditoria', desc: 'Consulte eventos reais de moderação e configuração.', action: 'Ver logs', tab: 'logs', icon: MessageSquare },
];

const METRICS = [
  ['Membros ativos', 'members', Users],
  ['Mensagens registradas', 'messages', MessageSquare],
  ['Avisos ativos', 'warnings', AlertTriangle],
  ['Tickets abertos', 'tickets', Ticket],
  ['Sugestões pendentes', 'pending_suggestions', Lightbulb],
  ['Moedas registradas', 'economy', Coins],
];

export default function OverviewTab({ guildId, setCurrentTab }) {
  const { user } = useAuth();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoading(true);
        setError(null);
        return apiRequest(`/guilds/${encodeURIComponent(guildId)}/overview`, { signal: controller.signal });
      })
      .then((data) => { if (!controller.signal.aborted && data !== null) setSummary(data); })
      .catch((failure) => { if (!controller.signal.aborted) setError(getApiErrorMessage(failure)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [guildId, retryCount]);

  const formatMetric = (value) => typeof value === 'number'
    ? value.toLocaleString('pt-BR', { maximumFractionDigits: 2 })
    : '-';

  return (
    <section className="space-y-6">
      <header className="dashboard-page-heading">
        <div>
          <h1 className="text-2xl font-semibold text-white">Bem-vindo, {user?.username || 'moderador'}</h1>
          <p className="mt-1 text-sm text-bn-muted">Resumo de dados reais registrados para o servidor selecionado.</p>
        </div>
      </header>

      {loading && <p role="status" className="rounded-lg border border-bn-border bg-bn-card p-5 text-sm text-bn-muted">Carregando resumo do servidor…</p>}
      {error && <div className="rounded-lg border border-red-500/30 bg-bn-card p-5"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={() => setRetryCount((current) => current + 1)} className="mt-3 inline-flex items-center gap-2 rounded-md bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}

      {!loading && !error && summary && (
        <div className="dashboard-metric-grid grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          {METRICS.map(([label, key, Icon]) => {
            const contents = (
              <>
              <div className="flex items-center gap-2.5">
                <span className="dashboard-metric-icon"><Icon size={16} strokeWidth={1.8} /></span>
                <p className="text-xs text-bn-muted">{label}</p>
              </div>
              <p className="mt-3 text-2xl font-semibold leading-none text-white">{formatMetric(summary[key])}</p>
              </>
            );
            return key === 'pending_suggestions' ? (
              <button key={key} type="button" className="dashboard-metric-card w-full cursor-pointer rounded-lg border border-bn-border bg-bn-card p-4 text-left" onClick={() => setShowSuggestions(true)} aria-haspopup="dialog" aria-label={`Ver sugestões pendentes: ${formatMetric(summary[key])}`}>
                {contents}
              </button>
            ) : (
              <article key={key} className="dashboard-metric-card rounded-lg border border-bn-border bg-bn-card p-4">
                {contents}
              </article>
            );
          })}
        </div>
      )}

      <div className="dashboard-section-panel rounded-lg border border-bn-border bg-bn-card">
        <div className="border-b border-bn-border px-4 py-3">
          <h2 className="text-sm font-medium text-white">Acesso rápido</h2>
          <p className="mt-1 text-xs text-bn-muted">Atalhos para as áreas de gerenciamento deste servidor.</p>
        </div>
        <div className="divide-y divide-bn-border">
          {QUICK_LINKS.map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.tab} className="dashboard-quick-link flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="dashboard-quick-icon"><Icon size={16} strokeWidth={1.8} /></span>
                  <span className="min-w-0"><span className="block text-sm font-medium text-white">{item.title}</span><span className="mt-1 block text-xs text-bn-muted">{item.desc}</span></span>
                </div>
                <button onClick={() => setCurrentTab(item.tab)} className="dashboard-quick-action self-start rounded-md border border-bn-border px-3 py-2 text-xs font-medium text-bn-muted sm:self-auto">{item.action}</button>
              </div>
            );
          })}
        </div>
      </div>
      {showSuggestions && <SuggestionsDialog guildId={guildId} onClose={() => setShowSuggestions(false)} />}
    </section>
  );
}
