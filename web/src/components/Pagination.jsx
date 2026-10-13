export default function Pagination({ page, pageSize, total, onPageChange, disabled = false }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between gap-3 border-t border-bn-border pt-4 text-xs text-bn-muted">
      <span>Página {page} de {totalPages} · {total} registro(s)</span>
      <div className="flex gap-2">
        <button disabled={disabled || page <= 1} onClick={() => onPageChange(page - 1)} className="rounded-lg border border-bn-border px-3 py-2 text-white disabled:opacity-40">Anterior</button>
        <button disabled={disabled || page >= totalPages} onClick={() => onPageChange(page + 1)} className="rounded-lg border border-bn-border px-3 py-2 text-white disabled:opacity-40">Próxima</button>
      </div>
    </div>
  );
}
