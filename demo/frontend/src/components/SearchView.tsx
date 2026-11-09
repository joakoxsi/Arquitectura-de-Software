import { FormEvent, useEffect, useRef, useState } from "react";
import { api, Channel, IndexNotReady, SearchHit, SearchParams, User } from "../api";
import { initials } from "./Sidebar";

type Sort = "recientes" | "antiguos" | "relevancia";
const SORTS: Record<Sort, Pick<SearchParams, "sort_by" | "sort_order">> = {
  recientes: { sort_by: "timestamp", sort_order: "desc" },
  antiguos: { sort_by: "timestamp", sort_order: "asc" },
  relevancia: { sort_by: "relevance", sort_order: "desc" },
};
const PAGE = 25;

interface Props {
  user: User;
  initialChannelId?: string;
  onOpenChannel: (channel: Channel) => void;
}

export default function SearchView({ user, initialChannelId, onOpenChannel }: Props) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [content, setContent] = useState("");
  const [channelId, setChannelId] = useState(initialChannelId ?? "");
  const [onlyMine, setOnlyMine] = useState(false);
  const [hasLink, setHasLink] = useState(false);
  const [hasMention, setHasMention] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [sort, setSort] = useState<Sort>("recientes");

  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [indexing, setIndexing] = useState(false);
  const retry = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => { api.listChannels().then(setChannels).catch(() => {}); }, []);
  useEffect(() => () => clearTimeout(retry.current), []);

  function params(offset: number): SearchParams {
    const has: ("link" | "mention")[] = [];
    if (hasLink) has.push("link");
    if (hasMention) has.push("mention");
    return {
      content: content.trim() || undefined,
      channel_id: channelId || undefined,
      author_id: onlyMine ? user.id : undefined,
      has,
      // Fechas del día completo en hora local, enviadas en ISO 8601.
      min_date: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
      max_date: to ? new Date(`${to}T23:59:59.999`).toISOString() : undefined,
      ...SORTS[sort],
      limit: PAGE,
      offset,
    };
  }

  async function run(offset = 0) {
    clearTimeout(retry.current);
    setLoading(true);
    setError(null);
    try {
      const result = await api.searchMessages(params(offset));
      setIndexing(false);
      setTotal(result.total_results);
      setHits((prev) => (offset === 0 ? result.messages : [...(prev ?? []), ...result.messages]));
    } catch (e) {
      if (e instanceof IndexNotReady) {
        setIndexing(true);
        retry.current = setTimeout(() => run(offset), 2000);
      } else {
        setError((e as Error).message);
      }
    } finally {
      setLoading(false);
    }
  }

  // Se busca al abrir la vista y cada vez que cambia un filtro (no al escribir).
  useEffect(() => { run(0); }, [channelId, onlyMine, hasLink, hasMention, from, to, sort]); // eslint-disable-line react-hooks/exhaustive-deps

  function submit(event: FormEvent) {
    event.preventDefault();
    run(0);
  }

  const scope = channels.find((c) => c.id === channelId);

  return (
    <section className="search">
      <header className="chat-header">
        <h2>Buscar mensajes</h2>
        <span className="muted small">{scope ? `en #${scope.name}` : "en todos los canales"}</span>
      </header>

      <form className="search-bar" onSubmit={submit}>
        <input
          autoFocus
          type="search"
          maxLength={1024}
          placeholder="Palabras a buscar (sin importar mayúsculas ni tildes)…"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <button className="btn primary" disabled={loading}>Buscar</button>
      </form>

      <div className="search-filters">
        <select value={channelId} onChange={(e) => setChannelId(e.target.value)} aria-label="Canal">
          <option value="">Todos los canales</option>
          {channels.map((c) => <option key={c.id} value={c.id}>#{c.name}</option>)}
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Orden">
          <option value="recientes">Más recientes</option>
          <option value="antiguos">Más antiguos</option>
          <option value="relevancia">Más relevantes</option>
        </select>
        <label className="date-field">Desde <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="date-field">Hasta <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></label>
        <button type="button" className={`toggle ${onlyMine ? "on" : ""}`} onClick={() => setOnlyMine((v) => !v)}>Mis mensajes</button>
        <button type="button" className={`toggle ${hasLink ? "on" : ""}`} onClick={() => setHasLink((v) => !v)}>Con enlace</button>
        <button type="button" className={`toggle ${hasMention ? "on" : ""}`} onClick={() => setHasMention((v) => !v)}>Con mención</button>
      </div>

      <div className="search-results">
        {indexing && <div className="banner info">El índice de búsqueda se está construyendo. Reintentando…</div>}
        {error && <div className="banner error">{error}</div>}
        {hits && !indexing && (
          <p className="muted small results-count">
            {total === 0 ? "Sin resultados." : `${total} resultado${total === 1 ? "" : "s"}`}
          </p>
        )}
        {hits?.map((hit) => (
          <button
            key={hit.id}
            className="result"
            onClick={() => onOpenChannel({ id: hit.channel_id, name: hit.channel_name ?? "canal" })}
            title="Abrir el canal"
          >
            <div className="avatar">{initials(hit.author_name)}</div>
            <div className="result-body">
              <div className="result-meta">
                <strong>{hit.author_name ?? "Usuario desconocido"}</strong>
                <span className="result-channel">#{hit.channel_name ?? "canal"}</span>
                <time>{new Date(hit.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</time>
              </div>
              <p className="result-content">
                {hit.highlights.length ? <Highlighted text={hit.highlights.join(" … ")} /> : hit.content}
              </p>
            </div>
          </button>
        ))}
        {hits && hits.length < total && (
          <button className="btn secondary load-more" disabled={loading} onClick={() => run(hits.length)}>
            {loading ? "Cargando…" : "Cargar más"}
          </button>
        )}
      </div>
    </section>
  );
}

/** El servicio marca las coincidencias con **…**; se muestran como <mark>. */
function Highlighted({ text }: { text: string }) {
  const parts = text.split("**");
  return <>{parts.map((part, i) => (i % 2 === 1 ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>))}</>;
}
