import { useCallback, useEffect, useState } from 'react';
import { Save, RotateCw, Settings } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';

const LOCALES = [
  { value: 'pt-BR', label: 'Português (Brasil)' },
  { value: 'en-US', label: 'English (United States)' },
];

export default function SettingsTab({ guildId }) {
  const [settings, setSettings] = useState(null);
  const [timezone, setTimezone] = useState('UTC');
  const [locale, setLocale] = useState('pt-BR');
  const [economyEnabled, setEconomyEnabled] = useState(false);
  const [levelsEnabled, setLevelsEnabled] = useState(false);
  const [analyticsEnabled, setAnalyticsEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  const load = useCallback(async (signal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/settings`, { signal });
      if (signal.aborted) return;
      setSettings(result);
      setTimezone(result.timezone);
      setLocale(result.locale);
      setEconomyEnabled(Boolean(result.economy_enabled));
      setLevelsEnabled(Boolean(result.levels_enabled));
      setAnalyticsEnabled(Boolean(result.analytics_enabled));
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

  const save = async (event) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/settings`, {
        method: 'PATCH',
        body: { timezone: timezone.trim(), locale, economy_enabled: economyEnabled, levels_enabled: levelsEnabled, analytics_enabled: analyticsEnabled },
      });
      setSettings(result);
      setTimezone(result.timezone);
      setLocale(result.locale);
      setEconomyEnabled(Boolean(result.economy_enabled));
      setLevelsEnabled(Boolean(result.levels_enabled));
      setAnalyticsEnabled(Boolean(result.analytics_enabled));
      setNotice('Configurações salvas no servidor.');
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="rounded-2xl border border-bn-border bg-bn-card p-8 text-sm text-bn-muted" role="status">Carregando configurações persistidas…</p>;
  if (!settings && error) return <section className="rounded-2xl border border-bn-border bg-bn-card p-8"><h2 className="font-bold text-white">Configurações indisponíveis</h2><p className="mt-2 text-sm text-red-300" role="alert">{error}</p><button onClick={() => setRetryCount((current) => current + 1)} className="mt-4 inline-flex items-center gap-2 rounded-xl bg-bn-dark px-4 py-2 text-sm text-white"><RotateCw className="h-4 w-4" /> Tentar novamente</button></section>;

  return (
    <form onSubmit={save} className="max-w-3xl space-y-6">
      <header><h2 className="flex items-center gap-2 text-2xl font-bold text-white"><Settings className="h-6 w-6 text-bn-green" /> Configurações gerais</h2><p className="mt-1 text-sm text-bn-muted">Valores carregados e salvos pela API do BN Bot.</p></header>
      {error && <p role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">{error}</p>}
      {notice && <p role="status" className="rounded-xl border border-bn-green/30 p-4 text-sm text-bn-green">{notice}</p>}
      <div className="rounded-2xl border border-bn-border bg-bn-card p-6">
        <label htmlFor="timezone" className="mb-2 block text-xs font-semibold uppercase text-bn-muted">Fuso horário IANA</label>
        <input id="timezone" required minLength={1} maxLength={64} disabled={saving} value={timezone} onChange={(event) => setTimezone(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white" />
        <p className="mt-2 text-xs text-bn-muted">Exemplo: America/Sao_Paulo, America/New_York ou UTC. O servidor verifica o identificador.</p>
        <label htmlFor="locale" className="mb-2 mt-5 block text-xs font-semibold uppercase text-bn-muted">Idioma</label>
        <select id="locale" value={locale} disabled={saving} onChange={(event) => setLocale(event.target.value)} className="w-full rounded-xl border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white">{LOCALES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select>
      </div>
      <div className="rounded-2xl border border-bn-border bg-bn-card p-6 space-y-5">
        <h3 className="font-bold text-white">Módulos do servidor</h3>
        {[[economyEnabled, setEconomyEnabled, 'economy', 'Economia'], [levelsEnabled, setLevelsEnabled, 'levels', 'Níveis e experiência'], [analyticsEnabled, setAnalyticsEnabled, 'analytics', 'Analytics']].map(([checked, setter, id, label]) => <label key={id} className="flex cursor-pointer items-center justify-between gap-4"><span className="text-sm text-white">{label}</span><input type="checkbox" checked={checked} disabled={saving} onChange={(event) => setter(event.target.checked)} aria-label={`Ativar ${label}`} className="h-5 w-5 accent-emerald-400" /></label>)}
      </div>
      <button disabled={saving} className="inline-flex items-center gap-2 rounded-xl bg-bn-green px-6 py-3 text-sm font-bold text-bn-dark disabled:opacity-60"><Save className="h-4 w-4" /> {saving ? 'Salvando…' : 'Salvar configurações'}</button>
    </form>
  );
}
