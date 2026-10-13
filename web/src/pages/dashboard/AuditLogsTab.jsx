import { useMemo, useState } from 'react';
import { FileText, RotateCw } from 'lucide-react';
import Pagination from '../../components/Pagination';
import { usePagedResource } from '../../hooks/usePagedResource';

const PAGE_SIZE = 25;

export default function AuditLogsTab({ guildId }) {
  const [page, setPage] = useState(1);
  const path = useMemo(() => `/guilds/${encodeURIComponent(guildId)}/audit`, [guildId]);
  const { data, loading, error, retry } = usePagedResource(path, page, PAGE_SIZE);

  return (
    <section className="space-y-6">
      <header><h2 className="flex items-center gap-2 text-2xl font-bold text-white"><FileText className="h-6 w-6 text-bn-green" /> Logs de auditoria</h2><p className="mt-1 text-sm text-bn-muted">Eventos de moderação, AutoMod e alterações de configuração que foram persistidos pelo sistema.</p></header>
      {loading && <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando logs…</p>}
      {error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-6"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
      {!loading && !error && data && data.items.length === 0 && <p className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Não há eventos de auditoria persistidos para este servidor.</p>}
      {!loading && !error && data?.items?.length > 0 && (
        <div className="rounded-2xl border border-bn-border bg-bn-card p-5">
          <div className="space-y-4">{data.items.map((event) => <article key={`${event.source}-${event.id}`} className="grid grid-cols-1 gap-2 border-b border-bn-border pb-4 last:border-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_180px]"><div><div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-white">{event.kind}</span><span className="rounded-md bg-bn-dark px-2 py-1 text-[10px] uppercase text-bn-muted">{event.source}</span></div><p className="mt-1 text-xs text-bn-muted">Ator: {event.actor_id || (event.source === 'automod' ? 'BN Bot / regra automática' : 'não registrado')} · Alvo/recurso: {event.target_id || '-'}</p>{event.reason && <p className="mt-2 text-sm text-bn-muted">{event.reason}</p>}</div><time className="text-xs text-bn-muted sm:text-right">{event.created_at ? new Date(event.created_at).toLocaleString('pt-BR') : 'Data indisponível'}</time></article>)}</div>
          <div className="mt-4"><Pagination page={data.page} pageSize={data.page_size} total={data.total} disabled={loading} onPageChange={setPage} /></div>
        </div>
      )}
    </section>
  );
}
