import { useEffect, useState } from 'react';
import { ArrowLeft, CalendarDays, ChevronRight, RotateCw, ThumbsDown, ThumbsUp, Trash2, UserRound, X } from 'lucide-react';
import { apiRequest, getApiErrorMessage } from '../../api/client';

function formatDate(value) {
  if (!value) return 'Data indisponível';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Data indisponível' : date.toLocaleString('pt-BR');
}

export default function SuggestionsDialog({ guildId, onClose }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [selected, setSelected] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        return apiRequest(`/guilds/${encodeURIComponent(guildId)}/suggestions`, { signal: controller.signal });
      })
      .then((data) => {
        if (!controller.signal.aborted && data !== null) setItems(Array.isArray(data?.items) ? data.items : []);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [guildId, retryCount]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div className="suggestion-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="suggestion-dialog" role="dialog" aria-modal="true" aria-labelledby="suggestion-dialog-title">
        <header className="suggestion-dialog-header">
          <div>
            {selected && <button type="button" className="suggestion-back-button" onClick={() => setSelected(null)}><ArrowLeft size={14} /> Voltar para sugestões</button>}
            <p className="suggestion-dialog-eyebrow">Comunidade</p>
            <h2 id="suggestion-dialog-title">{selected ? `Sugestão #${selected.id}` : 'Sugestões pendentes'}</h2>
          </div>
          <button type="button" className="suggestion-dialog-close" aria-label="Fechar sugestões" onClick={onClose}><X size={18} /></button>
        </header>

        {notice && <p role="status" className="suggestion-dialog-message">{notice}</p>}
        {loading && <p role="status" className="suggestion-dialog-message">Carregando sugestões…</p>}
        {!loading && error && (
          <div className="suggestion-dialog-message">
            <p role="alert">{error}</p>
            <button type="button" className="suggestion-retry-button" onClick={() => { setLoading(true); setError(null); setRetryCount((value) => value + 1); }}><RotateCw size={14} /> Tentar novamente</button>
          </div>
        )}
        {!loading && !error && !selected && items.length === 0 && <p className="suggestion-dialog-message">Não há sugestões pendentes neste servidor.</p>}

        {!loading && !error && !selected && items.length > 0 && (
          <div className="suggestion-dialog-list">
            {items.map((item) => (
              <button type="button" key={item.id} className="suggestion-list-item" onClick={() => setSelected(item)}>
                <span className="suggestion-list-copy">
                  <strong>Sugestão #{item.id}</strong>
                  <span>{item.content}</span>
                  <small><CalendarDays size={12} /> {formatDate(item.created_at)}</small>
                </span>
                <span className="suggestion-list-counts"><span><ThumbsUp size={13} /> {item.upvotes}</span><span><ThumbsDown size={13} /> {item.downvotes}</span></span>
                <ChevronRight size={16} className="suggestion-list-chevron" />
              </button>
            ))}
          </div>
        )}

        {!loading && !error && selected && (
          <div className="suggestion-detail">
            <span className="suggestion-status-label">Pendente</span>
            <p className="suggestion-detail-content">{selected.content}</p>
            <div className="suggestion-detail-meta">
              <span><UserRound size={14} /> Autor: {selected.author_id}</span>
              <span><CalendarDays size={14} /> {formatDate(selected.created_at)}</span>
              <span><ThumbsUp size={14} /> {selected.upvotes} apoios</span>
              <span><ThumbsDown size={14} /> {selected.downvotes} votos contra</span>
            </div>
            {selected.staff_note && <div className="suggestion-staff-note"><strong>Nota da equipe</strong><p>{selected.staff_note}</p></div>}
            {selected.channel_id && <p className="suggestion-detail-id">ID do canal: {selected.channel_id}</p>}
            <button
              type="button"
              className="suggestion-retry-button"
              disabled={deleting}
              onClick={async () => {
                if (!window.confirm(`Excluir permanentemente a sugestão #${selected.id}? Os votos vinculados também serão removidos.`)) return;
                setDeleting(true);
                setNotice(null);
                try {
                  await apiRequest(`/guilds/${encodeURIComponent(guildId)}/suggestions/${encodeURIComponent(selected.id)}`, { method: 'DELETE' });
                  setItems((current) => current.filter((item) => String(item.id) !== String(selected.id)));
                  setSelected(null);
                  setNotice(`Sugestão #${selected.id} excluída.`);
                } catch (failure) {
                  setNotice(`Não foi possível excluir a sugestão: ${getApiErrorMessage(failure)}`);
                } finally {
                  setDeleting(false);
                }
              }}
            >
              <Trash2 size={14} /> {deleting ? 'Excluindo…' : 'Excluir sugestão'}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
