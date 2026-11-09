import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { api, Channel, Message, User } from "../api";
import { usePolling } from "../usePolling";
import MessageItem from "./MessageItem";
import SummaryPanel from "./SummaryPanel";

interface Props { channel: Channel; user: User; onSearch: () => void }

export default function ChatView({ channel, user, onSearch }: Props) {
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  async function refresh() {
    try {
      setMessages(await api.listMessages(channel.id));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  usePolling(refresh, 2_500, [channel.id]);

  // Baja al final solo cuando llegan mensajes nuevos.
  useEffect(() => {
    const count = messages?.length ?? 0;
    if (count > lastCount.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
    lastCount.current = count;
  }, [messages]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    try {
      const message = await api.sendMessage(channel.id, user.id, content);
      setMessages((prev) => [...(prev ?? []), message]);
      setDraft("");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  return (
    <div className="chat-shell">
    <section className="chat">
      <header className="chat-header">
        <h2><span className="hash">#</span> {channel.name}</h2>
        <span className="muted small">{messages ? `${messages.length} mensajes` : "cargando…"}</span>
        <div className="header-actions">
          <button className="btn secondary small" onClick={onSearch}>⌕ Buscar en este canal</button>
          <button className={`btn small ${showSummary ? "primary" : "secondary"}`} onClick={() => setShowSummary((v) => !v)}>✦ Resumir</button>
        </div>
      </header>

      <div className="message-list" ref={listRef}>
        {messages?.length === 0 && (
          <div className="empty-state small">
            <p>No hay mensajes en <strong>#{channel.name}</strong>. ¡Escribe el primero!</p>
          </div>
        )}
        {messages?.map((message, i) => (
          <MessageItem
            key={message.id}
            message={message}
            mine={message.author_id === user.id}
            grouped={i > 0 && messages[i - 1].author_id === message.author_id}
          />
        ))}
      </div>

      {error && <div className="banner error">{error}</div>}

      <form className="composer" onSubmit={send}>
        <textarea
          rows={1}
          maxLength={4000}
          placeholder={`Escribe en #${channel.name}…  (Enter envía, Shift+Enter salto de línea)`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button className="btn primary" disabled={sending || !draft.trim()}>Enviar</button>
      </form>
    </section>
    {showSummary && <SummaryPanel channel={channel} user={user} onClose={() => setShowSummary(false)} />}
    </div>
  );
}
