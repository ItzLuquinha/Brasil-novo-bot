import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, BarChart3, Clock3, RefreshCw, Save, Settings2, ShieldCheck, Trash2, Users, MessageSquare, Mic, Plus } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';

const PERIODS = [
  { value: '24h', label: '24 horas' },
  { value: '7d', label: '7 dias' },
  { value: '30d', label: '30 dias' },
  { value: '90d', label: '90 dias' },
];

const COUNTER_METRICS = [
  { value: 'member_count', label: 'Membros totais', period: false },
  { value: 'human_members', label: 'Membros humanos', period: false },
  { value: 'bot_members', label: 'Bots', period: false },
  { value: 'voice_members', label: 'Membros em voz', period: false },
  { value: 'messages_period', label: 'Mensagens no período', period: true },
  { value: 'active_members_period', label: 'Membros ativos no período', period: true },
];

const number = (value) => Number(value || 0).toLocaleString('pt-BR');
const duration = (seconds) => {
  const value = Math.max(0, Number(seconds || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return `${hours.toLocaleString('pt-BR')}h ${String(minutes).padStart(2, '0')}min`;
};
const idText = (values) => (values || []).join(', ');
const parseIds = (value) => {
  if (!value.trim()) return [];
  const parts = value.split(',').map((part) => part.trim());
  if (parts.some((part) => !/^[1-9]\d{0,19}$/.test(part))) throw new Error('Informe somente IDs numéricos positivos separados por vírgulas.');
  const ids = [...new Set(parts)];
  if (ids.length > 200) throw new Error('Informe no máximo 200 IDs por lista.');
  return ids;
};

function StatCard({ label, value, detail, icon: Icon }) {
  return (
    <article className="rounded-xl border border-bn-border bg-bn-card p-4">
      <div className="flex items-center gap-2 text-xs text-bn-muted"><Icon size={16} /><span>{label}</span></div>
      <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
      {detail && <p className="mt-1 text-xs text-bn-muted">{detail}</p>}
    </article>
  );
}

function LineChart({ title, points, valueKey, valueLabel, color = '#72d6a0' }) {
  const values = points.map((point) => Math.max(0, Number(point[valueKey] || 0)));
  const max = Math.max(...values, 1);
  const polyline = values.map((value, index) => {
    const x = values.length <= 1 ? 360 : 24 + (index / (values.length - 1)) * 672;
    const y = 145 - (value / max) * 118;
    return `${x},${y}`;
  }).join(' ');
  return (
    <section className="min-w-0 rounded-xl border border-bn-border bg-bn-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-semibold text-white">{title}</h3><span className="text-xs text-bn-muted">{valueLabel}</span></div>
      {points.length === 0 ? <p className="mt-5 rounded-lg bg-bn-dark p-4 text-sm text-bn-muted">Ainda não há dados históricos para este período. O histórico começa a ser formado conforme o bot registra atividade.</p> : (
        <>
          <svg className="mt-3 h-44 w-full overflow-visible" viewBox="0 0 720 170" role="img" aria-label={title} preserveAspectRatio="none">
            {[27, 66, 105, 145].map((y) => <line key={y} x1="24" y1={y} x2="696" y2={y} stroke="#33404a" strokeWidth="1" />)}
            <polyline points={polyline} fill="none" stroke={color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
            {values.map((value, index) => {
              const x = values.length <= 1 ? 360 : 24 + (index / (values.length - 1)) * 672;
              const y = 145 - (value / max) * 118;
              return <circle key={`${points[index].bucket || points[index].date || points[index].hour}-${index}`} cx={x} cy={y} r="3.5" fill={color} />;
            })}
          </svg>
          <div className="mt-1 flex justify-between gap-3 text-[11px] text-bn-muted"><span>{points[0].date || (points[0].bucket ? new Date(points[0].bucket).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: undefined }) : `${points[0].hour}:00`)}</span><span>{points[points.length - 1].date || (points[points.length - 1].bucket ? new Date(points[points.length - 1].bucket).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: undefined }) : `${points[points.length - 1].hour}:00`)}</span></div>
        </>
      )}
    </section>
  );
}

function ErrorNotice({ value }) {
  return value ? <p role="alert" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{value}</p> : null;
}

export default function StatisticsTab({ guildId }) {
  const [period, setPeriod] = useState('7d');
  const [reportResult, setReportResult] = useState({ key: null, data: null, error: null });
  const [retryCount, setRetryCount] = useState(0);
  const [selectedChannelId, setSelectedChannelId] = useState('');
  const [channelReportResult, setChannelReportResult] = useState({ key: null, data: null, error: null });
  const [settings, setSettings] = useState(null);
  const [excludedChannels, setExcludedChannels] = useState('');
  const [excludedCategories, setExcludedCategories] = useState('');
  const [excludedRoles, setExcludedRoles] = useState('');
  const [excludeCommands, setExcludeCommands] = useState(true);
  const [excludeBots, setExcludeBots] = useState(true);
  const [trackVoice, setTrackVoice] = useState(true);
  const [memberStatisticsForManagers, setMemberStatisticsForManagers] = useState(true);
  const [retentionDays, setRetentionDays] = useState(365);
  const [counters, setCounters] = useState([]);
  const [rules, setRules] = useState([]);
  const [managementLoading, setManagementLoading] = useState(true);
  const [managementError, setManagementError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [savingSettings, setSavingSettings] = useState(false);
  const [savingCounter, setSavingCounter] = useState(false);
  const [savingRule, setSavingRule] = useState(false);
  const [counterChannel, setCounterChannel] = useState('');
  const [counterMetric, setCounterMetric] = useState('member_count');
  const [counterTemplate, setCounterTemplate] = useState('{label}: {value}');
  const [counterPeriod, setCounterPeriod] = useState('7');
  const [counterGoal, setCounterGoal] = useState('');
  const [ruleName, setRuleName] = useState('');
  const [ruleRole, setRuleRole] = useState('');
  const [ruleMessages, setRuleMessages] = useState('');
  const [ruleMessageDays, setRuleMessageDays] = useState('7');
  const [ruleVoice, setRuleVoice] = useState('');
  const [ruleVoiceDays, setRuleVoiceDays] = useState('7');
  const [ruleActiveDays, setRuleActiveDays] = useState('');
  const [ruleActiveWindow, setRuleActiveWindow] = useState('7');
  const [ruleEnabled, setRuleEnabled] = useState(true);
  const [removeWhenUnqualified, setRemoveWhenUnqualified] = useState(false);

  const loadManagement = useCallback(async (signal) => {
    setManagementLoading(true);
    setManagementError(null);
    try {
      const [settingsData, countersData, rulesData] = await Promise.all([
        apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/settings`, { signal }),
        apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/counters`, { signal }),
        apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/role-rules`, { signal }),
      ]);
      if (signal.aborted) return;
      setSettings(settingsData);
      setExcludedChannels(idText(settingsData.excluded_channel_ids));
      setExcludedCategories(idText(settingsData.excluded_category_ids));
      setExcludedRoles(idText(settingsData.excluded_role_ids));
      setExcludeCommands(Boolean(settingsData.exclude_commands));
      setExcludeBots(Boolean(settingsData.exclude_bots));
      setTrackVoice(Boolean(settingsData.track_voice));
      setMemberStatisticsForManagers(Boolean(settingsData.member_statistics_for_managers));
      setRetentionDays(settingsData.retention_days || 365);
      setCounters(countersData.items || []);
      setRules(rulesData.items || []);
    } catch (failure) {
      if (!signal.aborted) setManagementError(getApiErrorMessage(failure));
    } finally {
      if (!signal.aborted) setManagementLoading(false);
    }
  }, [guildId]);

  const reloadManagement = useCallback(async () => {
    const controller = new AbortController();
    await loadManagement(controller.signal);
  }, [loadManagement]);

  const reportRequestKey = JSON.stringify([guildId, period, retryCount]);
  const reportLoading = reportResult.key !== reportRequestKey;
  const report = reportResult.key === reportRequestKey ? reportResult.data : null;
  const reportError = reportResult.key === reportRequestKey ? reportResult.error : null;

  useEffect(() => {
    const controller = new AbortController();
    const requestKey = JSON.stringify([guildId, period, retryCount]);
    apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics?period=${encodeURIComponent(period)}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setReportResult({ key: requestKey, data, error: null });
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setReportResult({ key: requestKey, data: null, error: getApiErrorMessage(failure) });
      });
    return () => controller.abort();
  }, [guildId, period, retryCount]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve().then(() => {
      if (!controller.signal.aborted) loadManagement(controller.signal);
    });
    return () => controller.abort();
  }, [loadManagement, retryCount]);

  const chartPoints = useMemo(() => period === '24h'
    ? (report?.series || []).map((item) => ({ ...item, bucket: item.bucket }))
    : (report?.daily || []).map((item) => ({ ...item, bucket: item.date })), [period, report]);
  const memberCountPoints = useMemo(() => period === '24h'
    ? (report?.member_count_series || [])
    : (report?.daily_member_counts || []), [period, report]);
  const channelOptions = report?.top_channels || [];
  const activeChannelId = channelOptions.some((item) => String(item.channel_id) === selectedChannelId)
    ? selectedChannelId
    : String(channelOptions[0]?.channel_id || '');

  const channelRequestKey = JSON.stringify([guildId, activeChannelId, period, retryCount]);
  const channelReportLoading = Boolean(activeChannelId) && channelReportResult.key !== channelRequestKey;
  const channelReport = channelReportResult.key === channelRequestKey ? channelReportResult.data : null;
  const channelReportError = channelReportResult.key === channelRequestKey ? channelReportResult.error : null;

  useEffect(() => {
    if (!activeChannelId) return undefined;
    const controller = new AbortController();
    const requestKey = JSON.stringify([guildId, activeChannelId, period, retryCount]);
    const days = period === '24h' ? 1 : Number.parseInt(period, 10);
    apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/channels/${encodeURIComponent(activeChannelId)}?days=${days}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setChannelReportResult({ key: requestKey, data, error: null });
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setChannelReportResult({ key: requestKey, data: null, error: getApiErrorMessage(failure) });
      });
    return () => controller.abort();
  }, [guildId, activeChannelId, period, retryCount]);

  const action = async (callback, successMessage) => {
    setManagementError(null);
    setNotice(null);
    try {
      await callback();
      setNotice(successMessage);
      await reloadManagement();
    } catch (failure) {
      setManagementError(failure instanceof Error && failure.message && !failure.name.includes('ApiError') ? failure.message : getApiErrorMessage(failure));
    }
  };

  const saveSettings = async (event) => {
    event.preventDefault();
    if (savingSettings) return;
    setSavingSettings(true);
    await action(async () => {
      const result = await apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/settings`, {
        method: 'PATCH',
        body: {
          excluded_channel_ids: parseIds(excludedChannels),
          excluded_category_ids: parseIds(excludedCategories),
          excluded_role_ids: parseIds(excludedRoles),
          exclude_commands: excludeCommands,
          exclude_bots: excludeBots,
          track_voice: trackVoice,
          member_statistics_for_managers: memberStatisticsForManagers,
          retention_days: Number(retentionDays),
        },
      });
      setSettings(result);
    }, 'Filtros e configurações salvos. Os filtros novos valem para os dados registrados a partir de agora.');
    setSavingSettings(false);
  };

  const addCounter = async (event) => {
    event.preventDefault();
    if (savingCounter) return;
    setSavingCounter(true);
    await action(async () => {
      if (!/^[1-9]\d{0,19}$/.test(counterChannel.trim())) throw new Error('Informe um ID de canal válido.');
      const metric = COUNTER_METRICS.find((item) => item.value === counterMetric);
      await apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/counters`, {
        method: 'POST',
        body: {
          channel_id: counterChannel.trim(),
          metric: counterMetric,
          format_template: counterTemplate,
          period_days: metric?.period ? Number(counterPeriod) : null,
          goal_value: counterGoal.trim() ? Number(counterGoal) : null,
          enabled: true,
        },
      });
      setCounterChannel('');
      setCounterGoal('');
    }, 'Contador salvo. O bot tentará atualizar o canal de voz no próximo ciclo.');
    setSavingCounter(false);
  };

  const addRule = async (event) => {
    event.preventDefault();
    if (savingRule) return;
    setSavingRule(true);
    await action(async () => {
      if (!/^[1-9]\d{0,19}$/.test(ruleRole.trim())) throw new Error('Informe um ID de cargo válido.');
      const body = {
        name: ruleName.trim(),
        role_id: ruleRole.trim(),
        min_messages: ruleMessages.trim() ? Number(ruleMessages) : null,
        messages_window_days: Number(ruleMessageDays),
        min_voice_seconds: ruleVoice.trim() ? Number(ruleVoice) : null,
        voice_window_days: Number(ruleVoiceDays),
        min_active_days: ruleActiveDays.trim() ? Number(ruleActiveDays) : null,
        active_days_window_days: Number(ruleActiveWindow),
        enabled: ruleEnabled,
        remove_when_unqualified: removeWhenUnqualified,
      };
      if ([body.min_messages, body.min_voice_seconds, body.min_active_days].every((value) => value === null)) throw new Error('Configure pelo menos uma condição de atividade.');
      await apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/role-rules`, { method: 'POST', body });
      setRuleName('');
      setRuleRole('');
      setRuleMessages('');
      setRuleVoice('');
      setRuleActiveDays('');
    }, 'Regra salva. Confira o estado da regra após o próximo ciclo de avaliação.');
    setSavingRule(false);
  };

  const toggleCounter = (counter) => action(
    () => apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/counters/${encodeURIComponent(counter.id)}`, { method: 'PATCH', body: { enabled: !counter.enabled } }),
    counter.enabled ? 'Contador pausado.' : 'Contador reativado.',
  );
  const deleteCounter = (counter) => {
    if (!window.confirm(`Excluir o contador do canal ${counter.channel_id}? O canal do Discord não será excluído.`)) return;
    return action(() => apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/counters/${encodeURIComponent(counter.id)}`, { method: 'DELETE' }), 'Contador removido.');
  };
  const toggleRule = (rule) => action(
    () => apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/role-rules/${encodeURIComponent(rule.id)}`, { method: 'PATCH', body: { enabled: !rule.enabled } }),
    rule.enabled ? 'Regra pausada.' : 'Regra ativada.',
  );
  const toggleRuleRemoval = (rule) => {
    if (!rule.remove_when_unqualified && !window.confirm(`Ativar a remoção automática do cargo ${rule.role_id} quando os membros não cumprirem mais os requisitos?`)) return;
    return action(
      () => apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/role-rules/${encodeURIComponent(rule.id)}`, { method: 'PATCH', body: { remove_when_unqualified: !rule.remove_when_unqualified } }),
      'Política de remoção atualizada.',
    );
  };
  const deleteRule = (rule) => {
    if (!window.confirm(`Excluir a regra "${rule.name}"? Nenhum cargo será removido automaticamente por esta exclusão.`)) return;
    return action(() => apiRequest(`/guilds/${encodeURIComponent(guildId)}/analytics/role-rules/${encodeURIComponent(rule.id)}`, { method: 'DELETE' }), 'Regra removida.');
  };

  const totals = report?.totals || {};
  const comparison = report?.comparison || {};
  const comparisonText = (key) => comparison[key]?.change_percent == null ? 'Sem base para comparar' : `${comparison[key].change_percent > 0 ? '+' : ''}${comparison[key].change_percent}% sobre o período anterior`;
  const inputClass = 'w-full rounded-lg border border-bn-border bg-bn-dark px-3 py-2 text-sm text-white placeholder:text-bn-muted';
  const labelClass = 'mb-1.5 block text-xs font-medium text-bn-muted';
  const buttonClass = 'inline-flex items-center justify-center gap-2 rounded-lg bg-bn-green px-3 py-2 text-sm font-semibold text-bn-dark disabled:opacity-60';
  const secondaryButton = 'inline-flex items-center justify-center gap-2 rounded-lg border border-bn-border px-3 py-2 text-xs font-medium text-white hover:bg-bn-dark disabled:opacity-50';

  return (
    <section className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div><h1 className="flex items-center gap-2 text-2xl font-semibold text-white"><BarChart3 className="h-6 w-6 text-bn-green" /> Estatísticas e atividade</h1><p className="mt-1 max-w-3xl text-sm text-bn-muted">Análise de atividade, métricas históricas, contadores de canais e cargos automáticos. Os gráficos refletem somente os dados que o bot realmente registrou.</p></div>
        <div className="flex items-center gap-2"><label className="text-xs text-bn-muted" htmlFor="analytics-period">Período</label><select id="analytics-period" className={`${inputClass} w-auto min-w-32`} value={period} onChange={(event) => setPeriod(event.target.value)}>{PERIODS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><button type="button" onClick={() => setRetryCount((value) => value + 1)} className={secondaryButton} aria-label="Atualizar estatísticas"><RefreshCw size={14} /></button></div>
      </header>
      <ErrorNotice value={reportError} />
      <ErrorNotice value={managementError} />
      {notice && <p role="status" className="rounded-lg border border-bn-green/30 bg-bn-card p-3 text-sm text-bn-green">{notice}</p>}
      {reportLoading && <p role="status" className="rounded-lg border border-bn-border bg-bn-card p-4 text-sm text-bn-muted">Carregando métricas reais…</p>}
      {!reportLoading && report && (
        <>
          {!report.tracking_enabled && <p className="rounded-lg border border-amber-500/30 bg-bn-card p-3 text-sm text-amber-200">A coleta de analytics está desativada nas configurações gerais. Os dados históricos permanecem disponíveis; novas métricas não serão coletadas até a reativação.</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard label="Mensagens no período" value={number(totals.messages)} detail={comparisonText('messages')} icon={MessageSquare} />
            <StatCard label="Membros ativos" value={number(totals.active_members)} detail={comparisonText('active_members')} icon={Users} />
            <StatCard label="Tempo em voz registrado" value={duration(totals.voice_seconds)} detail={comparisonText('voice_seconds')} icon={Mic} />
            <StatCard label="Entradas" value={number(totals.joins)} detail={comparisonText('joins')} icon={Activity} />
            <StatCard label="Saídas" value={number(totals.leaves)} detail={comparisonText('leaves')} icon={Activity} />
            <StatCard label="Membros no último registro" value={number(totals.member_count)} detail={report.member_count_snapshot_available ? "Último snapshot histórico disponível" : "Contagem de membros registrados no banco; snapshot ainda não disponível"} icon={Users} />
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <LineChart title="Mensagens ao longo do período" points={chartPoints} valueKey="messages" valueLabel="Mensagens" />
            <LineChart title="Tempo em voz por período" points={chartPoints} valueKey="voice_seconds" valueLabel="Segundos" color="#94a9ff" />
            <LineChart title="Distribuição de mensagens por hora UTC" points={report.hourly_messages || []} valueKey="value" valueLabel="Mensagens" color="#f0bd75" />
          <LineChart title="Evolução do número de membros" points={memberCountPoints} valueKey="value" valueLabel="Membros" color="#e7a3e8" />
            <section className="rounded-xl border border-bn-border bg-bn-card p-4">
              <h3 className="font-semibold text-white">Canais mais ativos</h3>
              {!report.channel_details_available ? <p className="mt-4 text-sm text-bn-muted">O detalhamento por canal é restrito ao proprietário do servidor e aos administradores do BN Bot para proteger estatísticas de canais privados.</p> : (report.top_channels || []).length === 0 ? <p className="mt-4 text-sm text-bn-muted">Ainda não há atividade registrada por canal.</p> : <div className="mt-4 space-y-3">{report.top_channels.slice(0, 10).map((item) => { const max = Math.max(1, ...report.top_channels.map((row) => Number(row.messages || 0))); return <div key={item.channel_id}><div className="mb-1 flex justify-between gap-3 text-xs"><span className="truncate text-white">Canal {item.channel_id}</span><span className="text-bn-muted">{number(item.messages || 0)} mensagens</span></div><div className="h-2 overflow-hidden rounded-full bg-bn-dark"><div className="h-full rounded-full bg-bn-green" style={{ width: `${Math.max(0, Math.min(100, (Number(item.messages || 0) / max) * 100))}%` }} /></div></div>; })}</div>}
              <p className="mt-3 text-xs text-bn-muted">Os IDs são usados quando a API do dashboard não tem nomes de canais sincronizados.</p>
            </section>
          </div>
          <section className="rounded-xl border border-bn-border bg-bn-card p-4 sm:p-5">
            <header className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-semibold text-white">Análise de canal</h2><p className="mt-1 text-xs text-bn-muted">Detalhe histórico do canal selecionado, com membros únicos registrados.</p></div><label className="text-xs text-bn-muted">Canal<select className={`${inputClass} mt-1 min-w-40`} value={activeChannelId} onChange={(event) => setSelectedChannelId(event.target.value)}>{channelOptions.map((item) => <option key={item.channel_id} value={String(item.channel_id)}>Canal {item.channel_id}</option>)}</select></label></header>
            <ErrorNotice value={channelReportError} />
            {report && !report.channel_details_available ? <p className="text-sm text-bn-muted">O detalhamento individual por canal está restrito para proteger canais privados.</p> : !report ? <p className="text-sm text-bn-muted">Carregando permissões e estatísticas…</p> : channelReportLoading ? <p className="text-sm text-bn-muted">Carregando atividade do canal…</p> : channelReport ? <><div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3"><StatCard label="Mensagens" value={number(channelReport.totals.messages)} icon={MessageSquare} /><StatCard label="Tempo em voz" value={duration(channelReport.totals.voice_seconds)} icon={Mic} /><StatCard label="Membros únicos" value={number(channelReport.unique_active_members)} icon={Users} /></div><div className="grid grid-cols-1 gap-4 xl:grid-cols-2"><LineChart title="Mensagens no canal" points={channelReport.series || []} valueKey="messages" valueLabel="Mensagens" /><LineChart title="Tempo em voz no canal" points={channelReport.series || []} valueKey="voice_seconds" valueLabel="Segundos" color="#94a9ff" /></div></> : <p className="text-sm text-bn-muted">Ainda não há um canal com atividade suficiente para exibir detalhes.</p>}
          </section>
          <section className="overflow-hidden rounded-xl border border-bn-border bg-bn-card">
            <div className="border-b border-bn-border p-4"><h3 className="font-semibold text-white">Membros mais ativos</h3><p className="mt-1 text-xs text-bn-muted">Ranking calculado com as mensagens e sessões de voz registradas no período.</p></div>
            {(report.top_members || []).length === 0 ? <p className="p-4 text-sm text-bn-muted">{report.member_statistics_hidden ? 'Os detalhes individuais estão desativados nas configurações de privacidade.' : 'Ainda não há atividade suficiente para montar o ranking.'}</p> : <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="bg-bn-dark/50 text-xs uppercase text-bn-muted"><tr><th className="px-4 py-3">Membro</th><th className="px-4 py-3">Mensagens</th><th className="px-4 py-3">Voz</th></tr></thead><tbody>{report.top_members.map((item) => <tr key={item.user_id} className="border-t border-bn-border/70"><td className="px-4 py-3"><span className="block font-medium text-white">{item.display_name || item.username || 'Membro'}</span><span className="text-xs text-bn-muted">{item.user_id}</span></td><td className="px-4 py-3 text-white">{number(item.messages)}</td><td className="px-4 py-3 text-white">{duration(item.voice_seconds)}</td></tr>)}</tbody></table></div>}
            <div className="border-t border-bn-border p-4 text-xs text-bn-muted">Histórico disponível desde: {report.history_available_from ? new Date(report.history_available_from).toLocaleString('pt-BR') : 'ainda não há dados históricos'}.</div>
          </section>
        </>
      )}

      <section className="rounded-xl border border-bn-border bg-bn-card p-4 sm:p-5">
        <header className="mb-4 flex items-center gap-2"><Settings2 className="h-5 w-5 text-bn-green" /><div><h2 className="font-semibold text-white">Filtros e retenção</h2><p className="mt-1 text-xs text-bn-muted">As mudanças controlam novos registros. Não reescrevem o histórico anterior.</p></div></header>
        {managementLoading && !settings ? <p role="status" className="text-sm text-bn-muted">Carregando configurações…</p> : (
          <form onSubmit={saveSettings} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div><label className={labelClass} htmlFor="excluded-channels">IDs de canais excluídos</label><input id="excluded-channels" value={excludedChannels} onChange={(event) => setExcludedChannels(event.target.value)} className={inputClass} placeholder="123..., 456..." /><p className="mt-1 text-xs text-bn-muted">Separados por vírgula.</p></div>
              <div><label className={labelClass} htmlFor="excluded-categories">IDs de categorias excluídas</label><input id="excluded-categories" value={excludedCategories} onChange={(event) => setExcludedCategories(event.target.value)} className={inputClass} placeholder="IDs de categoria" /></div>
              <div><label className={labelClass} htmlFor="excluded-roles">IDs de cargos excluídos</label><input id="excluded-roles" value={excludedRoles} onChange={(event) => setExcludedRoles(event.target.value)} className={inputClass} placeholder="IDs de cargo" /></div>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              {[[excludeCommands, setExcludeCommands, 'Excluir comandos da contagem'], [excludeBots, setExcludeBots, 'Excluir bots'], [trackVoice, setTrackVoice, 'Registrar atividade em voz'], [memberStatisticsForManagers, setMemberStatisticsForManagers, 'Permitir detalhes individuais aos gestores do servidor']].map(([checked, setChecked, label]) => <label key={label} className="flex items-start gap-2 rounded-lg bg-bn-dark p-3 text-sm text-white"><input type="checkbox" checked={checked} onChange={(event) => setChecked(event.target.checked)} className="mt-0.5 h-4 w-4 accent-emerald-400" /><span>{label}</span></label>)}
            </div>
            <div className="max-w-xs"><label className={labelClass} htmlFor="retention-days">Retenção do histórico (dias)</label><input id="retention-days" type="number" min="30" max="3650" value={retentionDays} onChange={(event) => setRetentionDays(event.target.value)} className={inputClass} required /><p className="mt-1 text-xs text-bn-muted">Entre 30 e 3650 dias. A limpeza é feita em lotes pelo worker.</p></div>
            <button disabled={savingSettings} className={buttonClass}><Save size={15} /> {savingSettings ? 'Salvando…' : 'Salvar configurações'}</button>
          </form>
        )}
      </section>

      <section className="rounded-xl border border-bn-border bg-bn-card p-4 sm:p-5">
        <header className="mb-4 flex items-center gap-2"><Activity className="h-5 w-5 text-bn-green" /><div><h2 className="font-semibold text-white">Contadores automáticos</h2><p className="mt-1 text-xs text-bn-muted">Informe o ID de um canal de voz ou palco que o bot possa gerenciar.</p></div></header>
        <form onSubmit={addCounter} className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
          <div className="xl:col-span-2"><label className={labelClass} htmlFor="counter-channel">ID do canal de voz</label><input id="counter-channel" value={counterChannel} onChange={(event) => setCounterChannel(event.target.value)} className={inputClass} placeholder="ID do Discord" required pattern="[1-9][0-9]{0,19}" /></div>
          <div className="xl:col-span-2"><label className={labelClass} htmlFor="counter-metric">Métrica</label><select id="counter-metric" value={counterMetric} onChange={(event) => setCounterMetric(event.target.value)} className={inputClass}>{COUNTER_METRICS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div>
          <div className="xl:col-span-2"><label className={labelClass} htmlFor="counter-format">Nome do canal</label><input id="counter-format" value={counterTemplate} onChange={(event) => setCounterTemplate(event.target.value)} className={inputClass} maxLength={100} required /><p className="mt-1 text-xs text-bn-muted">Campos: {'{label}'}, {'{value}'}, {'{goal}'}, {'{percent}'}.</p></div>
          {COUNTER_METRICS.find((item) => item.value === counterMetric)?.period && <div><label className={labelClass} htmlFor="counter-days">Período em dias</label><input id="counter-days" type="number" min="1" max="365" value={counterPeriod} onChange={(event) => setCounterPeriod(event.target.value)} className={inputClass} required /></div>}
          <div><label className={labelClass} htmlFor="counter-goal">Meta (opcional)</label><input id="counter-goal" type="number" min="1" max="2000000000" value={counterGoal} onChange={(event) => setCounterGoal(event.target.value)} className={inputClass} placeholder="Ex.: 1500" /></div>
          <div className="flex items-end"><button disabled={savingCounter} className={buttonClass}><Plus size={15} /> {savingCounter ? 'Salvando…' : 'Adicionar contador'}</button></div>
        </form>
        <div className="mt-5 divide-y divide-bn-border rounded-lg border border-bn-border">
          {counters.length === 0 ? <p className="p-4 text-sm text-bn-muted">Nenhum contador configurado.</p> : counters.map((counter) => <div key={counter.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><p className="font-medium text-white">{counter.metric_label} · canal {counter.channel_id}</p><p className="mt-1 break-words text-xs text-bn-muted">Formato: {counter.format_template} · Último valor: {counter.last_value == null ? 'Ainda não calculado' : number(counter.last_value)}</p>{counter.last_error && <p role="status" className="mt-1 text-xs text-amber-200">{counter.last_error}</p>}{counter.last_updated_at && <p className="mt-1 text-xs text-bn-muted">Sincronizado: {new Date(counter.last_updated_at).toLocaleString('pt-BR')}</p>}</div><div className="flex shrink-0 gap-2"><button type="button" onClick={() => toggleCounter(counter)} className={secondaryButton}>{counter.enabled ? 'Pausar' : 'Ativar'}</button><button type="button" onClick={() => deleteCounter(counter)} className={secondaryButton} aria-label={`Excluir contador do canal ${counter.channel_id}`}><Trash2 size={14} /> Excluir</button></div></div>)}
        </div>
      </section>

      <section className="rounded-xl border border-bn-border bg-bn-card p-4 sm:p-5">
        <header className="mb-4 flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-bn-green" /><div><h2 className="font-semibold text-white">Cargos automáticos por atividade</h2><p className="mt-1 text-xs text-bn-muted">O bot valida a hierarquia e bloqueia cargos administradores ou privilegiados. Remoção automática fica desativada por padrão.</p></div></header>
        <form onSubmit={addRule} className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div><label className={labelClass} htmlFor="rule-name">Nome da regra</label><input id="rule-name" value={ruleName} onChange={(event) => setRuleName(event.target.value)} className={inputClass} maxLength={100} required /></div>
          <div><label className={labelClass} htmlFor="rule-role">ID do cargo</label><input id="rule-role" value={ruleRole} onChange={(event) => setRuleRole(event.target.value)} className={inputClass} required pattern="[1-9][0-9]{0,19}" /></div>
          <div><label className={labelClass} htmlFor="rule-messages">Mensagens mínimas (opcional)</label><input id="rule-messages" type="number" min="1" max="1000000" value={ruleMessages} onChange={(event) => setRuleMessages(event.target.value)} className={inputClass} /></div>
          <div><label className={labelClass} htmlFor="rule-message-days">Janela de mensagens (dias)</label><input id="rule-message-days" type="number" min="1" max="365" value={ruleMessageDays} onChange={(event) => setRuleMessageDays(event.target.value)} className={inputClass} /></div>
          <div><label className={labelClass} htmlFor="rule-voice">Segundos em voz mínimos (opcional)</label><input id="rule-voice" type="number" min="1" max="31536000" value={ruleVoice} onChange={(event) => setRuleVoice(event.target.value)} className={inputClass} /></div>
          <div><label className={labelClass} htmlFor="rule-voice-days">Janela de voz (dias)</label><input id="rule-voice-days" type="number" min="1" max="365" value={ruleVoiceDays} onChange={(event) => setRuleVoiceDays(event.target.value)} className={inputClass} /></div>
          <div><label className={labelClass} htmlFor="rule-active-days">Dias ativos mínimos (opcional)</label><input id="rule-active-days" type="number" min="1" max="365" value={ruleActiveDays} onChange={(event) => setRuleActiveDays(event.target.value)} className={inputClass} /></div>
          <div><label className={labelClass} htmlFor="rule-active-window">Janela de dias ativos</label><input id="rule-active-window" type="number" min="1" max="365" value={ruleActiveWindow} onChange={(event) => setRuleActiveWindow(event.target.value)} className={inputClass} /></div>
          <div className="flex flex-col gap-2 rounded-lg bg-bn-dark p-3 text-sm text-white"><label className="flex items-center gap-2"><input type="checkbox" checked={ruleEnabled} onChange={(event) => setRuleEnabled(event.target.checked)} className="accent-emerald-400" /> Regra ativada</label><label className="flex items-center gap-2"><input type="checkbox" checked={removeWhenUnqualified} onChange={(event) => setRemoveWhenUnqualified(event.target.checked)} className="accent-emerald-400" /> Remover se perder os requisitos</label></div>
          <div className="flex items-end"><button disabled={savingRule} className={buttonClass}><Plus size={15} /> {savingRule ? 'Salvando…' : 'Criar regra'}</button></div>
        </form>
        <div className="mt-5 divide-y divide-bn-border rounded-lg border border-bn-border">
          {rules.length === 0 ? <p className="p-4 text-sm text-bn-muted">Nenhuma regra configurada.</p> : rules.map((rule) => <div key={rule.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{rule.name}</p><span className={`rounded px-2 py-0.5 text-[11px] ${rule.enabled ? 'bg-bn-green/10 text-bn-green' : 'bg-bn-dark text-bn-muted'}`}>{rule.enabled ? 'Ativa' : 'Pausada'}</span></div><p className="mt-1 text-xs text-bn-muted">Cargo {rule.role_id} · {rule.min_messages == null ? 'sem requisito de mensagens' : `${number(rule.min_messages)} mensagens em ${rule.messages_window_days} dias`} · {rule.min_voice_seconds == null ? 'sem requisito de voz' : `${duration(rule.min_voice_seconds)} em ${rule.voice_window_days} dias`} · {rule.min_active_days == null ? 'sem requisito de dias ativos' : `${rule.min_active_days} dias ativos em ${rule.active_days_window_days} dias`}</p><p className="mt-1 text-xs text-bn-muted">Remoção automática: {rule.remove_when_unqualified ? 'ativada' : 'desativada'}. Última avaliação: {rule.last_evaluated_at ? new Date(rule.last_evaluated_at).toLocaleString('pt-BR') : 'aguardando o worker'}.</p>{rule.last_error && <p role="status" className="mt-1 text-xs text-amber-200">{rule.last_error}</p>}</div><div className="flex shrink-0 flex-wrap gap-2"><button type="button" onClick={() => toggleRule(rule)} className={secondaryButton}>{rule.enabled ? 'Pausar' : 'Ativar'}</button><button type="button" onClick={() => toggleRuleRemoval(rule)} className={secondaryButton}>{rule.remove_when_unqualified ? 'Desativar remoção' : 'Ativar remoção'}</button><button type="button" onClick={() => deleteRule(rule)} className={secondaryButton} aria-label={`Excluir regra ${rule.name}`}><Trash2 size={14} /> Excluir</button></div></div>)}
        </div>
      </section>
      <p className="flex items-start gap-2 text-xs text-bn-muted"><Clock3 size={14} className="mt-0.5 shrink-0" /> As métricas históricas começam na primeira coleta. Mudanças nos filtros são aplicadas aos próximos eventos; ao ativar o rastreamento de voz, membros que já estavam conectados podem precisar mudar de canal ou reconectar para iniciar a coleta da sessão. Cargos e contadores são processados por workers periódicos.</p>
      {settings && <p className="text-xs text-bn-muted">Retenção configurada: {settings.retention_days} dias. As regras de atividade e os contadores são isolados para este servidor.</p>}
      {managementLoading && <p className="text-xs text-bn-muted">Atualizando configurações…</p>}
    </section>
  );
}
