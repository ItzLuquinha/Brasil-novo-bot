import {
  Home,
  Settings,
  ShieldAlert,
  Shield,
  Coins,
  FileText,
  Users,
  Activity,
  Server,
  LogOut,
  LogIn,
  User,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

export default function Sidebar({ currentTab, setCurrentTab, guild, mobileOpen = false, onClose }) {
  const navigate = useNavigate();
  const { user, logout, login } = useAuth();

  const items = [
    { id: 'overview', label: 'Início / Overview', icon: Home },
    { id: 'servers', label: 'Servidores', icon: Server, action: () => navigate('/servers') },
    { id: 'automod', label: 'Auto Moderation', icon: ShieldAlert },
    { id: 'moderation', label: 'Casos de Moderação', icon: Shield },
    { id: 'economy', label: 'Economia & Loja', icon: Coins },
    { id: 'members', label: 'Membros & Níveis', icon: Users },
    { id: 'statistics', label: 'Estatísticas', icon: Activity },
    { id: 'logs', label: 'Logs de Auditoria', icon: FileText },
    { id: 'settings', label: 'Configurações Gerais', icon: Settings },
  ];

  const closeMenu = () => onClose?.();
  const avatarUrl = user?.avatar && user?.id
    ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png`
    : null;

  return (
    <>
      {mobileOpen && <button type="button" className="dashboard-sidebar-backdrop" aria-label="Fechar menu" onClick={closeMenu} />}
      <aside className={`dashboard-sidebar${mobileOpen ? ' is-open' : ''}`} aria-label="Navegação principal">
        <div className="dashboard-brand">
          <button type="button" className="dashboard-brand-button" onClick={() => { navigate('/'); closeMenu(); }} aria-label="Ir para a página inicial do BN Bot">
            <span className="dashboard-brand-mark" aria-hidden="true"><span>B</span><span>N</span></span>
            <span className="dashboard-brand-copy">
              <strong>BN Bot</strong>
              <small>Web Dashboard</small>
            </span>
          </button>
        </div>



        <nav className="dashboard-nav">
          {items.map(({ id, label, icon: Icon, action }) => {
            const active = currentTab === id;
            return (
              <button
                type="button"
                key={id}
                aria-current={active ? 'page' : undefined}
                className={`dashboard-nav-item${active ? ' is-active' : ''}`}
                onClick={() => {
                  if (!user) {
                    if (id === 'overview') navigate('/');
                    else login();
                    closeMenu();
                    return;
                  }
                  if (action) action();
                  else if (guild) setCurrentTab(id);
                  else if (id === 'overview') navigate('/');
                  else navigate('/servers');
                  closeMenu();
                }}
              >
                <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>

        <div className="dashboard-account">
          {avatarUrl ? (
            <img src={avatarUrl} alt="" className="dashboard-account-avatar" />
          ) : (
            <span className="dashboard-account-avatar dashboard-account-fallback"><User size={16} /></span>
          )}
          <span className="dashboard-account-copy">
            <strong>{user?.username || 'Não conectado'}</strong>
            <small>{user?.system_role || 'Conta Discord'}</small>
          </span>
          {user ? (
            <button type="button" className="dashboard-logout" title="Sair da conta" aria-label="Sair da conta" onClick={logout}>
              <LogOut size={15} strokeWidth={1.8} />
            </button>
          ) : (
            <button type="button" className="dashboard-logout" title="Entrar com Discord" aria-label="Entrar com Discord" onClick={login}>
              <LogIn size={15} strokeWidth={1.8} />
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
