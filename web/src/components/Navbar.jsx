import { LogOut, Menu, User } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

const TAB_TITLES = {
  overview: 'Visão geral',
  servers: 'Servidores',
  settings: 'Configurações gerais',
  automod: 'Auto Moderation',
  moderation: 'Casos de moderação',
  economy: 'Economia & Loja',
  members: 'Membros & Níveis',
  logs: 'Logs de auditoria',
};

export default function Navbar({ guildName, currentTab = 'overview', onToggleSidebar, onNavigateToOverview, showAccount = false }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const avatarUrl = user?.avatar && user?.id
    ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
    : null;

  return (
    <header className="dashboard-topbar">
      <div className="dashboard-topbar-title">
        {onToggleSidebar && <button type="button" className="dashboard-menu-toggle" aria-label="Abrir navegação" onClick={onToggleSidebar}><Menu size={19} /></button>}
        <div className="dashboard-breadcrumbs">
          <button type="button" className="dashboard-breadcrumb-link" onClick={() => navigate('/')} aria-label="Voltar para a página inicial do BN Bot">BN Bot</button>
          {guildName && <><span className="dashboard-breadcrumb-separator">/</span><button type="button" className="dashboard-breadcrumb-link" onClick={() => { if (onNavigateToOverview) onNavigateToOverview(); else navigate('/servers'); }} aria-label={`Abrir visão geral de ${guildName}`}>{guildName}</button></>}
          <span className="dashboard-breadcrumb-separator">/</span>
          <strong aria-current="page">{TAB_TITLES[currentTab] || 'Dashboard'}</strong>
        </div>
      </div>
      {showAccount && (
        <div className="dashboard-topbar-account">
          {avatarUrl ? <img src={avatarUrl} alt="" className="dashboard-topbar-avatar" /> : <User size={16} />}
          <span>{user?.username || 'Conta Discord'}</span>
          <button type="button" className="dashboard-topbar-logout" title="Sair da conta" aria-label="Sair da conta" onClick={logout}><LogOut size={15} /></button>
        </div>
      )}
    </header>
  );
}
