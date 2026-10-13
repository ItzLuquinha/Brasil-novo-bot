import { useMemo, useState } from 'react';
import { RotateCw, Users } from 'lucide-react';
import Pagination from '../../components/Pagination';
import { usePagedResource } from '../../hooks/usePagedResource';

const PAGE_SIZE = 25;

export default function MembersTab({ guildId }) {
  const [page, setPage] = useState(1);
  const path = useMemo(() => `/guilds/${encodeURIComponent(guildId)}/members`, [guildId]);
  const { data, loading, error, retry } = usePagedResource(path, page, PAGE_SIZE);

  return (
    <section className="space-y-6">
      <header><h2 className="flex items-center gap-2 text-2xl font-bold text-white"><Users className="h-6 w-6 text-bn-green" /> Membros e níveis</h2><p className="mt-1 text-sm text-bn-muted">Membros ativos registrados pelo bot, ordenados por atividade. A experiência vem da persistência de níveis existente.</p></header>
      {loading && <p role="status" className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando membros…</p>}
      {error && <div className="rounded-2xl border border-red-500/30 bg-bn-card p-6"><p role="alert" className="text-sm text-red-200">{error}</p><button onClick={retry} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-bn-dark px-3 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></div>}
      {!loading && !error && data && data.items.length === 0 && <p className="rounded-2xl border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Nenhum membro ativo foi registrado no banco de dados deste servidor.</p>}
      {!loading && !error && data?.items?.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-bn-border bg-bn-card">
          <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="border-b border-bn-border bg-bn-dark/60 text-xs uppercase text-bn-muted"><tr><th className="px-5 py-4">Membro</th><th className="px-5 py-4">Nível</th><th className="px-5 py-4">XP</th><th className="px-5 py-4">Mensagens</th><th className="px-5 py-4">Atividade</th><th className="px-5 py-4">Entrou em</th></tr></thead><tbody>{data.items.map((member) => <tr key={member.user_id} className="border-b border-bn-border/70 last:border-b-0"><td className="px-5 py-4"><div className="flex items-center gap-3">{member.avatar_url ? <img src={member.avatar_url} alt="" className="h-8 w-8 rounded-full" /> : <div className="h-8 w-8 rounded-full bg-bn-dark" />}<div><span className="block font-semibold text-white">{member.display_name || member.username || 'Usuário Discord'}</span><span className="block text-xs text-bn-muted">@{member.username || member.user_id}</span></div></div></td><td className="px-5 py-4 text-white">{member.level ?? '-'}</td><td className="px-5 py-4 text-white">{member.xp?.toLocaleString('pt-BR') ?? '-'}</td><td className="px-5 py-4 text-white">{member.messages.toLocaleString('pt-BR')}</td><td className="px-5 py-4 text-white">{member.activity.toLocaleString('pt-BR')}</td><td className="px-5 py-4 text-bn-muted">{member.joined_at ? new Date(member.joined_at).toLocaleDateString('pt-BR') : '-'}</td></tr>)}</tbody></table></div>
          <div className="p-5"><Pagination page={data.page} pageSize={data.page_size} total={data.total} disabled={loading} onPageChange={setPage} /></div>
        </div>
      )}
    </section>
  );
}
