import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, RotateCw } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';
import Sidebar from '../../components/Sidebar';
import Navbar from '../../components/Navbar';
import OverviewTab from './OverviewTab';
import AutoModTab from './AutoModTab';
import SettingsTab from './SettingsTab';
import ModerationTab from './ModerationTab';
import EconomyTab from './EconomyTab';
import MembersTab from './MembersTab';
import AuditLogsTab from './AuditLogsTab';
import StatisticsTab from './StatisticsTab';

const SNOWFLAKE = /^[1-9]\d{0,19}$/;

export default function GuildDashboard() {
  const { guildId } = useParams();
  const navigate = useNavigate();
  const [guild, setGuild] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [currentTab, setCurrentTab] = useState('overview');
  const [retryCount, setRetryCount] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleTabChange = (tab) => {
    setCurrentTab(tab);
  };

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        if (!guildId || !SNOWFLAKE.test(guildId)) {
          setGuild(null);
          setError('O identificador deste servidor é inválido.');
          return null;
        }
        setLoading(true);
        setError(null);
        setGuild(null);
        return apiRequest(`/guilds/${encodeURIComponent(guildId)}`, { signal: controller.signal });
      })
      .then((data) => {
        if (!controller.signal.aborted && data !== null) setGuild(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [guildId, retryCount]);

  let content;
  if (loading || (!error && guild?.id !== guildId)) {
    content = <p role="status" className="rounded-lg border border-bn-border bg-bn-card p-6 text-sm text-bn-muted">Carregando dados do servidor…</p>;
  } else if (error) {
    content = (
      <div className="max-w-2xl rounded-lg border border-red-500/30 bg-bn-card p-6">
        <div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 h-5 w-5 text-red-300" /><div><h1 className="font-semibold text-white">Não foi possível abrir este servidor</h1><p role="alert" className="mt-2 text-sm text-red-200">{error}</p></div></div>
        <div className="mt-5 flex flex-wrap gap-3"><button onClick={() => setRetryCount((value) => value + 1)} className="inline-flex items-center gap-2 rounded-md bg-bn-green px-4 py-2 text-sm font-semibold text-bn-dark"><RotateCw className="h-4 w-4" /> Tentar novamente</button><button onClick={() => navigate('/servers')} className="rounded-md border border-bn-border px-4 py-2 text-sm text-white">Voltar aos servidores</button></div>
      </div>
    );
  } else if (!guild) {
    content = <p role="alert" className="rounded-lg border border-bn-border bg-bn-card p-5 text-sm text-bn-muted">Servidor indisponível.</p>;
  } else {
    content = (
      <div className="dashboard-tab-panels">



        <div hidden={currentTab !== 'overview'}><OverviewTab guildId={guildId} setCurrentTab={handleTabChange} /></div>
        <div hidden={currentTab !== 'automod'}><AutoModTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'moderation'}><ModerationTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'economy'}><EconomyTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'members'}><MembersTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'statistics'}><StatisticsTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'logs'}><AuditLogsTab guildId={guildId} /></div>
        <div hidden={currentTab !== 'settings'}><SettingsTab guildId={guildId} /></div>
      </div>
    );
  }

  return (
    <div className="dashboard-shell">
      <Sidebar currentTab={currentTab} setCurrentTab={handleTabChange} guild={guild} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
      <div className="dashboard-main">
        <Navbar guildName={guild?.name} currentTab={currentTab} onNavigateToOverview={() => handleTabChange('overview')} onToggleSidebar={() => setMobileOpen((value) => !value)} />
        <main className="dashboard-content">{content}</main>
      </div>
    </div>
  );
}
