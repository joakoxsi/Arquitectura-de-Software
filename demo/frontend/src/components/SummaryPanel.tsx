import { useEffect, useRef, useState } from "react";
import { api, Channel, Summary, SummaryState, User } from "../api";

const STATE_LABEL: Record<SummaryState, string> = {
  pendiente: "En cola…",
  procesando: "Generando…",
  completada: "Listo",
  fallida: "Falló",
};
const POLL_MS = 1500;

interface Props { channel: Channel; user: User; onClose: () => void }

/** Panel de resúmenes del canal (servicio summaries, vía gateway).
 *  Pedir un resumen es asíncrono: el POST devuelve un id y aquí se consulta hasta terminar. */
export default function SummaryPanel({ channel, user, onClose }: Props) {
  const [mode, setMode] = useState<"nuevo" | "fechas">("nuevo");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [history, setHistory] = useState<Summary[]>([]);
  const [selected, setSelected] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const poll = useRef<ReturnType<typeof setTimeout>>();

  async function loadHistory(selectFirst = false) {
    try {
      const list = await api.listSummaries(channel.id);
      setHistory(list);
      if (selectFirst) setSelected(list[0] ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    loadHistory(true);
    return () => clearTimeout(poll.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel.id]);

  function follow(summaryId: string) {
    clearTimeout(poll.current);
    poll.current = setTimeout(async () => {
      try {
        const summary = await api.getSummary(summaryId);
        setSelected(summary);
        if (summary.messageState === "completada" || summary.messageState === "fallida") {
          setBusy(false);
          loadHistory();
        } else {
          follow(summaryId);
        }
      } catch (e) {
        setBusy(false);
        setError((e as Error).message);
      }
    }, POLL_MS);
  }

  async function generate() {
    setError(null);
    let timeInterval;
    if (mode === "fechas") {
      if (!from || !to) return setError("Elige el inicio y el fin del rango.");
      const start = new Date(from);
      const end = new Date(to);
      if (start >= end) return setError("El inicio debe ser anterior al fin.");
      timeInterval = { start: start.toISOString(), end: end.toISOString() };
    }
    setBusy(true);
    try {
      const { summary_id } = await api.requestSummary(channel.id, { user_id: user.id, timeInterval });
      setSelected(await api.getSummary(summary_id));
      follow(summary_id);
    } catch (e) {
      setBusy(false);
      setError((e as Error).message);
    }
  }

  return (
    <aside className="summary-panel">
      <header className="summary-head">
        <h3>✦ Resumen de #{channel.name}</h3>
        <button className="icon-btn dark" title="Cerrar" onClick={onClose}>×</button>
      </header>

      <div className="summary-controls">
        <div className="segmented wide">
          <button className={mode === "nuevo" ? "active" : ""} onClick={() => setMode("nuevo")}>Lo nuevo</button>
          <button className={mode === "fechas" ? "active" : ""} onClick={() => setMode("fechas")}>Por fechas</button>
        </div>
        {mode === "nuevo" ? (
          <p className="muted small">Resume los mensajes que aún no entraron en un resumen anterior.</p>
        ) : (
          <div className="summary-range">
            <label>Desde <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label>Hasta <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></label>
          </div>
        )}
        <button className="btn primary block" disabled={busy} onClick={generate}>
          {busy ? "Generando resumen…" : "Generar resumen"}
        </button>
        {error && <p className="error small">{error}</p>}
      </div>

      <div className="summary-body">
        {selected ? <SummaryCard summary={selected} /> : (
          <p className="muted small">Este canal aún no tiene resúmenes.</p>
        )}

        {history.length > 0 && (
          <>
            <h4 className="summary-history-title">Anteriores</h4>
            <ul className="summary-history">
              {history.map((s) => (
                <li key={s.id}>
                  <button className={s.id === selected?.id ? "active" : ""} onClick={() => setSelected(s)}>
                    <span className={`dot ${s.messageState}`} />
                    <span>{formatDate(s.created_at)}</span>
                    <span className="muted">{s.timeInterval ? "por fechas" : "lo nuevo"}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </aside>
  );
}

function SummaryCard({ summary }: { summary: Summary }) {
  const s = summary.structured;
  return (
    <div className="summary-card">
      <div className="summary-card-head">
        <span className={`badge state-${summary.messageState}`}>{STATE_LABEL[summary.messageState]}</span>
        <span className="muted small">
          {summary.timeInterval
            ? `${formatDate(summary.timeInterval.start)} → ${formatDate(summary.timeInterval.end)}`
            : formatDate(summary.created_at)}
        </span>
      </div>

      {(summary.messageState === "pendiente" || summary.messageState === "procesando") && (
        <div className="summary-loading"><span className="spinner" /> El modelo está leyendo la conversación…</div>
      )}
      {summary.messageState === "fallida" && <p className="error small">{summary.error}</p>}

      {s && (
        <>
          <p className="summary-overview">{s.overview}</p>
          <Section title="Decisiones" items={s.decisions.map((d) => d)} />
          <Section title="Eventos" items={s.events.map((e) => (e.when ? `${e.description} · ${e.when}` : e.description))} />
          <Section title="Tareas" items={s.tasks.map((t) => (t.assignee ? `${t.description} → ${t.assignee}` : t.description))} />
        </>
      )}
    </div>
  );
}

function Section({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="summary-section">
      <h4>{title}</h4>
      <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul>
    </div>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
}
