import { useMemo, useState } from 'react';
import { Shield, RotateCw } from 'lucide-react';
import Pagination from '../../components/Pagination';
import { usePagedResource } from '../../hooks/usePagedResource';

const PAGE_SIZE = 25;

export default function ModerationTab({ guildId }) {
  const [page, setPage] = useState(1);
  const path = useMemo(() => `/guilds/${encodeURIComponent(guildId)}/moderation`, [guildId]);
  const { data, loading, error, retry } = usePagedResource(path, page, PAGE_SIZE);

  return (
    <section className="space-y-6">
      <header><h2 className="flex items-center gap-2 text-2xl font-bold text-white"><Shield className="h-6 w-6 text-bn-green" /> Casos de moderação</h2><p className="mt-1 text-sm text-bn-muted">Histórico de ações de moderação já persistidas. Ações novas continuam sendo executadas pelos comandos com as permissões do Discord.</p></header>
      {loading && <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando casos…</p>}
      {error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-6"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
      {!loading && !error && data && data.items.length === 0 && <p className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Nenhum caso de moderação foi registrado neste servidor.</p>}
      {!loading && !error && data?.items?.length > 0 && <div className="rounded-2xl border border-bn-border bg-bn-card p-5"><div className="space-y-4">{data.items.map((item) => <article key={item.id} className="flex flex-col justify-between gap-3 border-b border-bn-border pb-4 last:border-0 last:pb-0 sm:flex-row"><div><p className="font-semibold text-white">{item.kind}</p><p className="mt-1 text-xs text-bn-muted">Moderador: {item.actor_id} · Alvo: {item.target_id || '-'}</p>{item.reason && <p className="mt-2 text-sm text-bn-muted">{item.reason}</p>}</div><time className="text-xs text-bn-muted">{item.created_at ? new Date(item.created_at).toLocaleString('pt-BR') : 'Data indisponível'}</time></article>)}</div><div className="mt-4"><Pagination page={data.page} pageSize={data.page_size} total={data.total} disabled={loading} onPageChange={setPage} /></div></div>}
    </section>
  );
}
