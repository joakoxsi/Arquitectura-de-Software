import { FormEvent, useState } from "react";
import { api, Channel, User } from "../api";
import { usePolling } from "../usePolling";

interface Props {
  user: User;
  activeChannelId: string | null;
  glossaryActive: boolean;
  searchActive: boolean;
  onSelectChannel: (channel: Channel) => void;
  onOpenGlossary: () => void;
  onOpenSearch: () => void;
  onLogout: () => void;
}

export default function Sidebar(props: Props) {
  const { user, activeChannelId, glossaryActive, searchActive, onSelectChannel, onOpenGlossary, onOpenSearch, onLogout } = props;
  const [channels, setChannels] = useState<Channel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [copied, setCopied] = useState(false);

  async function refresh() {
    try {
      setChannels(await api.listChannels());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  usePolling(refresh, 10_000, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    const text = name.trim();
    if (!text) return;
    try {
      const channel = await api.createChannel(text);
      setName("");
      setCreating(false);
      await refresh();
      onSelectChannel(channel);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copyId() {
    try {
      await navigator.clipboard.writeText(user.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* portapapeles no disponible */ }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="brand-mark small">C</span>
        <span>Chat Microsvcs</span>
      </div>

      <button className={`sidebar-search ${searchActive ? "active" : ""}`} onClick={onOpenSearch}>
        <span aria-hidden>⌕</span> Buscar mensajes
      </button>

      <div className="sidebar-section channels">
        <div className="section-header">
          <span>Canales</span>
          <button className="icon-btn" title="Nuevo canal" onClick={() => setCreating((v) => !v)}>
            {creating ? "×" : "+"}
          </button>
        </div>
        {creating && (
          <form className="new-channel" onSubmit={create}>
            <input autoFocus maxLength={80} placeholder="nombre-del-canal" value={name} onChange={(e) => setName(e.target.value)} />
          </form>
        )}
        <ul className="channel-list">
          {channels.map((channel) => (
            <li key={channel.id}>
              <button className={channel.id === activeChannelId ? "active" : ""} onClick={() => onSelectChannel(channel)}>
                <span className="hash">#</span> {channel.name}
              </button>
            </li>
          ))}
          {channels.length === 0 && !error && <li className="muted small">Aún no hay canales.</li>}
        </ul>
        {error && <p className="error small">{error}</p>}
      </div>

      <div className="sidebar-section">
        <div className="section-header"><span>Ozy</span></div>
        <ul className="channel-list">
          <li>
            <button className={glossaryActive ? "active" : ""} onClick={onOpenGlossary}>
              <span className="hash">≡</span> Glosario
            </button>
          </li>
        </ul>
      </div>

      <div className="sidebar-user">
        <div className="avatar">{initials(user.display_name)}</div>
        <div className="user-info">
          <strong>{user.display_name}</strong>
          <button className="link" onClick={copyId} title={user.id}>{copied ? "¡id copiado!" : "copiar mi id"}</button>
        </div>
        <button className="icon-btn" title="Cambiar usuario" onClick={onLogout}>⎋</button>
      </div>
    </aside>
  );
}

export function initials(name: string | null | undefined) {
  if (!name) return "?";
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
}
