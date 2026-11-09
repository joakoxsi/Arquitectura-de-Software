import { useState } from "react";
import { api, AudienceLevel, LEVELS, Message, Translation } from "../api";
import { initials } from "./Sidebar";

const LEVEL_LABEL: Record<AudienceLevel, string> = {
  basico: "Básico",
  intermedio: "Intermedio",
  experto: "Experto",
};

interface Props { message: Message; mine: boolean; grouped: boolean }

export default function MessageItem({ message, mine, grouped }: Props) {
  const [open, setOpen] = useState(false);
  const [level, setLevel] = useState<AudienceLevel>("basico");
  const [translations, setTranslations] = useState<Partial<Record<AudienceLevel, Translation>>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(next: AudienceLevel) {
    setLevel(next);
    setOpen(true);
    if (translations[next]) return;
    setLoading(true);
    setError(null);
    try {
      const t = await api.translate(message.id, message.channel_id, next);
      setTranslations((prev) => ({ ...prev, [next]: t }));
    } catch (e) {
      const err = e as { status?: number; message: string };
      setError(err.status === 404
        ? "Ozy aún no recibe este mensaje. Intenta de nuevo en unos segundos."
        : err.message);
    } finally {
      setLoading(false);
    }
  }

  const current = translations[level];
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <article className={`message ${grouped ? "grouped" : ""} ${mine ? "mine" : ""}`}>
      {!mine && <div className="avatar">{grouped ? "" : initials(message.author_name)}</div>}
      <div className="message-body">
        {!grouped && !mine && (
          <div className="message-meta">
            <strong>{message.author_name ?? "Usuario desconocido"}</strong>
          </div>
        )}
        <div className="bubble">
          <p className="message-content">{message.content}</p>
          <time>{time}</time>
        </div>

        <div className="message-actions">
          <button className="chip" onClick={() => (open ? setOpen(false) : load(level))}>
            {open ? "Ocultar explicación" : "Explicar en simple"}
          </button>
        </div>

        {open && (
          <div className="translation">
            <div className="translation-head">
              <span className="ozy-tag">Ozy</span>
              <div className="segmented">
                {LEVELS.map((l) => (
                  <button key={l} className={l === level ? "active" : ""} onClick={() => load(l)}>
                    {LEVEL_LABEL[l]}
                  </button>
                ))}
              </div>
            </div>
            {loading && <p className="muted small">Traduciendo…</p>}
            {error && <p className="error small">{error}</p>}
            {current && !loading && (
              <>
                <p>{current.explanation}</p>
                {current.terms.length > 0 && (
                  <ul className="terms">
                    {current.terms.map((term) => (
                      <li key={term.term}>
                        <span className="term">{term.term}</span>
                        {!term.known && <span className="badge candidato">candidato</span>}
                        {term.ambiguous && <span className="badge ambiguo">ambiguo</span>}
                        {term.meanings.map((m, i) => (
                          <span key={i} className="badge ambito">{String(m.ambito)}</span>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
