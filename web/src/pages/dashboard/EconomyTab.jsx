import { useMemo, useState } from 'react';
import { Coins, RotateCw } from 'lucide-react';
import Pagination from '../../components/Pagination';
import { usePagedResource } from '../../hooks/usePagedResource';

const PAGE_SIZE = 25;
const formatMoney = (value) => Number(value || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function EconomyTab({ guildId }) {
  const [page, setPage] = useState(1);
  const path = useMemo(() => `/guilds/${encodeURIComponent(guildId)}/economy`, [guildId]);
  const { data, loading, error, retry } = usePagedResource(path, page, PAGE_SIZE);

  return (
    <section className="space-y-6">
      <header><h2 className="flex items-center gap-2 text-2xl font-bold text-white"><Coins className="h-6 w-6 text-bn-green" /> Economia e loja</h2><p className="mt-1 text-sm text-bn-muted">Saldos reais persistidos. A edição de carteira e banco permanece nos comandos de administração do bot; esta tela não simula operações financeiras.</p></header>
      {loading && <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando saldos…</p>}
      {error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-6"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
      {!loading && !error && data && data.items.length === 0 && <p className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Ainda não há contas de economia persistidas neste servidor.</p>}
      {!loading && !error && data?.items?.length > 0 && <div className="overflow-hidden rounded-2xl border border-bn-border bg-bn-card"><div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead className="border-b border-bn-border bg-bn-dark/60 text-xs uppercase text-bn-muted"><tr><th className="px-5 py-4">ID do membro</th><th className="px-5 py-4">Carteira</th><th className="px-5 py-4">Banco</th><th className="px-5 py-4">Total</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.user_id} className="border-b border-bn-border/70 last:border-0"><td className="px-5 py-4 text-white">{item.user_id}</td><td className="px-5 py-4 text-white">{formatMoney(item.wallet)}</td><td className="px-5 py-4 text-white">{formatMoney(item.bank)}</td><td className="px-5 py-4 font-semibold text-bn-green">{formatMoney(item.total)}</td></tr>)}</tbody></table></div><div className="p-5"><Pagination page={data.page} pageSize={data.page_size} total={data.total} disabled={loading} onPageChange={setPage} /></div></div>}
    </section>
  );
}
