import { useCallback, useEffect, useState } from 'react';
import { Save, ShieldAlert, RotateCw, Settings2, Trash2, Plus } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';

const ACTIONS = [
  { value: 'delete', label: 'Apagar mensagem' },
  { value: 'warn', label: 'Advertir' },
  { value: 'timeout', label: 'Silenciar (timeout)' },
  { value: 'kick', label: 'Expulsar' },
  { value: 'ban', label: 'Banir' },
  { value: 'none', label: 'Somente detectar' },
];

const ACTIONS_WITHOUT_NONE = ACTIONS.filter((action) => action.value !== 'none');

export default function AutoModTab({ guildId }) {
  const [data, setData] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [blacklistAction, setBlacklistAction] = useState('delete');
  const [rules, setRules] = useState([]);
  const [lists, setLists] = useState([]);
  const [listType, setListType] = useState('blacklist');
  const [entryType, setEntryType] = useState('word');
  const [entryValue, setEntryValue] = useState('');
  const [entryReason, setEntryReason] = useState('');
  const [listSaving, setListSaving] = useState(false);
  const [deletingEntryId, setDeletingEntryId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [initializing, setInitializing] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  const load = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/automod`, { signal });
      if (signal.aborted) return;
      setData(result);
      if (result.configured) {
        setEnabled(Boolean(result.enabled));
        setBlacklistAction(result.blacklist_action || 'delete');
        setRules(Array.isArray(result.rules) ? result.rules : []);
        setLists(Array.isArray(result.lists) ? result.lists : []);
      } else {
        setEnabled(false);
        setBlacklistAction('delete');
        setRules([]);
        setLists([]);
      }
    } catch (failure) {
      if (!signal.aborted) setError(getApiErrorMessage(failure));
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, [guildId]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve().then(() => {
      if (!controller.signal.aborted) load(controller.signal);
    });
    return () => controller.abort();
  }, [load, retryCount]);

  const updateRule = (ruleId, patch) => {
    setRules((current) => current.map((rule) => rule.id === ruleId ? { ...rule, ...patch } : rule));
    setNotice(null);
  };

  const initializeDefaults = async () => {
    if (initializing) return;
    setInitializing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/automod/setup`, { method: 'POST' });
      setData(result);
      setEnabled(Boolean(result.enabled));
      setBlacklistAction(result.blacklist_action || 'delete');
      setRules(Array.isArray(result.rules) ? result.rules : []);
      setLists(Array.isArray(result.lists) ? result.lists : []);
      setNotice('Configuração inicial persistida no servidor.');
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setInitializing(false);
    }
  };

  const save = async () => {
    if (!data?.configured || saving) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {
        enabled,
        blacklist_action: blacklistAction,
        rules: rules.map((rule) => ({
          id: rule.id,
          enabled: Boolean(rule.enabled),
          action: rule.action,
          priority: Number(rule.priority),
          channel_ids: rule.channel_ids || [],
          role_ids: rule.role_ids || [],
          config: rule.config || {},
        })),
      };
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/automod`, { method: 'PUT', body: payload });
      setData(result);
      setEnabled(Boolean(result.enabled));
      setBlacklistAction(result.blacklist_action || 'delete');
      setRules(Array.isArray(result.rules) ? result.rules : []);
      setLists(Array.isArray(result.lists) ? result.lists : []);
      setNotice('Alterações salvas e confirmadas pela API. O bot as aplica após atualizar seu cache.');
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setSaving(false);
    }
  };

  const addListEntry = async (event) => {
    event.preventDefault();
    if (listSaving || !entryValue.trim()) return;
    setListSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/automod/lists`, {
        method: 'POST',
        body: { list_type: listType, entry_type: entryType, value: entryValue.trim(), reason: entryReason.trim() || null },
      });
      setLists((current) => [...current.filter((item) => item.id !== created.id), created]);
      setEntryValue('');
      setEntryReason('');
      setNotice('Entrada adicionada e confirmada pelo servidor.');
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setListSaving(false);
    }
  };

  const deleteListEntry = async (entryId) => {
    if (deletingEntryId !== null) return;
    setDeletingEntryId(entryId);
    setError(null);
    setNotice(null);
    try {
      await apiRequest(`/guilds/${encodeURIComponent(guildId)}/automod/lists/${entryId}`, { method: 'DELETE' });
      setLists((current) => current.filter((entry) => entry.id !== entryId));
      setNotice('Entrada removida do servidor.');
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setDeletingEntryId(null);
    }
  };

  if (loading) {
    return <div className="max-w-3xl rounded-2xl border border-bn-border bg-bn-card p-8 text-sm text-bn-muted" role="status">Carregando configuração persistida do AutoMod…</div>;
  }

  if (error && !data) {
    return (
      <section className="max-w-3xl rounded-2xl border border-bn-border bg-bn-card p-8">
        <h2 className="text-lg font-bold text-white">Não foi possível carregar o AutoMod</h2>
        <p className="mt-2 text-sm text-red-300" role="alert">{error}</p>
        <button onClick={() => setRetryCount((value) => value + 1)} className="mt-5 inline-flex items-center gap-2 rounded-xl bg-bn-dark px-4 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button>
      </section>
    );
  }

  if (!data?.configured) {
    return (
      <section className="max-w-3xl rounded-2xl border border-bn-border bg-bn-card p-8">
        <div className="flex items-center gap-3"><ShieldAlert className="h-6 w-6 text-bn-green" /><h2 className="text-xl font-bold text-white">AutoMod ainda não configurado</h2></div>
        <p className="mt-3 text-sm text-bn-muted">Não há configurações persistidas para este servidor. A ação abaixo cria as regras iniciais suportadas pelo bot sem sobrescrever regras existentes.</p>
        {error && <p className="mt-3 text-sm text-red-300" role="alert">{error}</p>}
        <button disabled={initializing} onClick={initializeDefaults} className="mt-6 inline-flex items-center gap-2 rounded-xl bg-bn-green px-5 py-3 text-sm font-bold text-bn-dark disabled:opacity-60"><Settings2 className="h-4 w-4" /> {initializing ? 'Configurando…' : 'Criar regras iniciais'}</button>
      </section>
    );
  }

  return (
    <section className="max-w-4xl space-y-6">
      <header className="mb-2">
        <h2 className="flex items-center gap-2 text-2xl font-bold text-white"><ShieldAlert className="h-6 w-6 text-bn-green" /> AutoMod</h2>
        <p className="mt-1 text-sm text-bn-muted">As alterações são validadas e gravadas no banco de dados utilizado pelo bot.</p>
      </header>

      {error && <p className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200" role="alert">{error}</p>}
      {notice && <p className="rounded-xl border border-bn-green/30 p-4 text-sm text-bn-green" role="status">{notice}</p>}

      <div className="rounded-2xl border border-bn-border bg-bn-card p-6">
        <label className="flex cursor-pointer items-center justify-between gap-4">
          <span><span className="block text-sm font-bold text-white">Ativar proteção automática</span><span className="mt-1 block text-xs text-bn-muted">O bot processará as regras ativas deste servidor.</span></span>
          <input aria-label="Ativar proteção automática" type="checkbox" checked={enabled} disabled={saving} onChange={(event) => { setEnabled(event.target.checked); setNotice(null); }} className="h-5 w-5 accent-emerald-400" />
        </label>
        <div className="mt-5 max-w-sm">
          <label htmlFor="blacklist-action" className="mb-2 block text-xs font-semibold uppercase text-bn-muted">Ação da blacklist</label>
          <select id="blacklist-action" value={blacklistAction} disabled={saving} onChange={(event) => { setBlacklistAction(event.target.value); setNotice(null); }} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white">
            {ACTIONS_WITHOUT_NONE.map((action) => <option key={action.value} value={action.value}>{action.label}</option>)}
          </select>
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-lg font-bold text-white">Regras persistidas ({rules.length})</h3>
        {rules.length === 0 ? (
          <div className="rounded-xl border border-bn-border bg-bn-card p-5">
            <p className="text-sm text-bn-muted">Nenhuma regra está configurada. O botão abaixo cria as regras padrão ausentes sem sobrescrever entradas existentes.</p>
            <button type="button" disabled={initializing || saving} onClick={initializeDefaults} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-bn-dark px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Settings2 className="h-4 w-4" /> {initializing ? 'Configurando…' : 'Criar regras padrão'}</button>
          </div>
        ) : rules.map((rule) => (
          <article key={rule.id} className="rounded-2xl border border-bn-border bg-bn-card p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div><h4 className="font-bold text-white">{rule.name}</h4><p className="mt-1 text-xs text-bn-muted">Tipo: {rule.rule_type} · Prioridade: {rule.priority}</p></div>
              <label className="flex items-center gap-2 text-xs text-bn-muted"><input type="checkbox" checked={Boolean(rule.enabled)} disabled={saving} onChange={(event) => updateRule(rule.id, { enabled: event.target.checked })} className="h-4 w-4 accent-emerald-400" /> Regra ativa</label>
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor={`action-${rule.id}`} className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Ação</label>
                <select id={`action-${rule.id}`} value={rule.action} disabled={saving} onChange={(event) => updateRule(rule.id, { action: event.target.value })} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white">
                  {ACTIONS.map((action) => <option key={action.value} value={action.value}>{action.label}</option>)}
                </select>
              </div>
              {rule.rule_type === 'mentions' && (
                <div>
                  <label htmlFor={`mentions-${rule.id}`} className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Limite de menções</label>
                  <input id={`mentions-${rule.id}`} type="number" min="1" max="100" step="1" disabled={saving} value={rule.config?.max_total ?? 5} onChange={(event) => updateRule(rule.id, { config: { ...(rule.config || {}), max_total: event.target.value === '' ? '' : Number(event.target.value) } })} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white" />
                </div>
              )}
              <div>
                <label htmlFor={`priority-${rule.id}`} className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Prioridade</label>
                <input id={`priority-${rule.id}`} type="number" min="-10000" max="10000" step="1" disabled={saving} value={rule.priority} onChange={(event) => updateRule(rule.id, { priority: event.target.value === '' ? '' : Number(event.target.value) })} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white" />
              </div>
            </div>
            {rule.rule_type === 'invite' && <p className="mt-3 text-xs text-bn-muted">Esta regra detecta convites do Discord conforme a implementação do bot.</p>}
          </article>
        ))}
      </div>

      <section className="space-y-4 rounded-2xl border border-bn-border bg-bn-card p-6">
        <div><h3 className="text-lg font-bold text-white">Listas de exceção e bloqueio</h3><p className="mt-1 text-xs text-bn-muted">Entradas persistidas usadas pelo mecanismo AutoMod do bot.</p></div>
        <form onSubmit={addListEntry} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div><label htmlFor="automod-list-type" className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Lista</label><select id="automod-list-type" value={listType} disabled={saving || listSaving} onChange={(event) => setListType(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white"><option value="blacklist">Bloqueio</option><option value="whitelist">Exceção</option></select></div>
          <div><label htmlFor="automod-entry-type" className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Tipo de entrada</label><select id="automod-entry-type" value={entryType} disabled={saving || listSaving} onChange={(event) => setEntryType(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white"><option value="word">Palavra</option><option value="domain">Domínio</option><option value="user">ID de usuário</option><option value="channel">ID de canal</option><option value="role">ID de cargo</option></select></div>
          <div><label htmlFor="automod-entry-value" className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Valor</label><input id="automod-entry-value" required minLength={1} maxLength={500} disabled={saving || listSaving} value={entryValue} onChange={(event) => setEntryValue(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white" placeholder={entryType === 'domain' ? 'example.com' : entryType === 'word' ? 'palavra ou expressão' : 'ID numérico do Discord'} /></div>
          <div><label htmlFor="automod-entry-reason" className="mb-1.5 block text-xs font-semibold uppercase text-bn-muted">Motivo (opcional)</label><input id="automod-entry-reason" maxLength={500} disabled={saving || listSaving} value={entryReason} onChange={(event) => setEntryReason(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white" placeholder="Contexto para a equipe" /></div>
          <button type="submit" disabled={saving || listSaving || !entryValue.trim()} className="inline-flex items-center justify-center gap-2 rounded-xl bg-bn-dark px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 sm:col-span-2"><Plus className="h-4 w-4" /> {listSaving ? 'Adicionando…' : 'Adicionar entrada'}</button>
        </form>
        {lists.length === 0 ? <p className="rounded-xl border border-bn-border p-4 text-sm text-bn-muted">Nenhuma entrada de lista foi cadastrada.</p> : <div className="divide-y divide-bn-border">{lists.map((entry) => <div key={entry.id} className="flex flex-wrap items-center justify-between gap-3 py-3"><div className="min-w-0"><p className="break-all text-sm font-semibold text-white">{entry.value}</p><p className="mt-1 text-xs text-bn-muted">{entry.list_type === 'blacklist' ? 'Bloqueio' : 'Exceção'} · {entry.entry_type}{entry.reason ? ` · ${entry.reason}` : ''}</p></div><button type="button" disabled={saving || listSaving || deletingEntryId !== null} onClick={() => deleteListEntry(entry.id)} aria-label={`Remover entrada ${entry.value}`} className="inline-flex items-center gap-2 rounded-lg border border-bn-border px-3 py-2 text-xs text-bn-muted hover:text-red-300 disabled:opacity-50"><Trash2 className="h-4 w-4" />{deletingEntryId === entry.id ? 'Removendo…' : 'Remover'}</button></div>)}</div>}
      </section>

      <button disabled={saving || listSaving || deletingEntryId !== null} onClick={save} className="inline-flex items-center gap-2 rounded-xl bg-bn-green px-6 py-3 text-sm font-bold text-bn-dark disabled:cursor-not-allowed disabled:opacity-60"><Save className="h-4 w-4" /> {saving ? 'Salvando…' : 'Salvar alterações'}</button>
    </section>
  );
}
