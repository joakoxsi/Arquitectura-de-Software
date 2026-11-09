import { FormEvent, useMemo, useState } from "react";
import { Ambito, AMBITOS, api, Estado, GlossaryEntry, User } from "../api";
import { usePolling } from "../usePolling";

const ESTADOS: Estado[] = ["candidato", "validado", "rechazado"];

export default function GlossaryView({ user }: { user: User }) {
  const [entries, setEntries] = useState<GlossaryEntry[]>([]);
  const [ambito, setAmbito] = useState<Ambito | "">("");
  const [estado, setEstado] = useState<Estado | "">("");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<GlossaryEntry | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setEntries(await api.listGlossary(ambito || undefined, estado || undefined));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  usePolling(refresh, 8_000, [ambito, estado]);

  // Un término es ambiguo si tiene definiciones utilizables en más de un ámbito.
  const ambiguous = useMemo(() => {
    const scopes = new Map<string, Set<string>>();
    for (const e of entries) {
      if (!e.definition || !e.ambito || e.estado === "rechazado") continue;
      const key = e.term.toLowerCase();
      scopes.set(key, (scopes.get(key) ?? new Set()).add(e.ambito));
    }
    return new Set([...scopes].filter(([, s]) => s.size > 1).map(([k]) => k));
  }, [entries]);

  const visible = entries
    .filter((e) => e.term.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => a.term.localeCompare(b.term));

  return (
    <section className="glossary">
      <header className="chat-header">
        <h2>Glosario de Ozy</h2>
        <span className="muted small">{visible.length} términos</span>
      </header>

      <div className="filters">
        <input placeholder="Buscar término…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select value={ambito} onChange={(e) => setAmbito(e.target.value as Ambito | "")}>
          <option value="">Todos los ámbitos</option>
          {AMBITOS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select value={estado} onChange={(e) => setEstado(e.target.value as Estado | "")}>
          <option value="">Todos los estados</option>
          {ESTADOS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {error && <div className="banner error">{error}</div>}

      <div className="glossary-grid">
        {visible.map((entry) => (
          <div key={entry.id} className={`term-card ${entry.estado}`}>
            <div className="term-card-head">
              <span className="term">{entry.term}</span>
              <span className={`badge ${entry.estado}`}>{entry.estado}</span>
            </div>
            <div className="term-card-tags">
              {entry.ambito && <span className="badge ambito">{entry.ambito}</span>}
              {ambiguous.has(entry.term.toLowerCase()) && <span className="badge ambiguo">ambiguo</span>}
            </div>
            <p className={entry.definition ? "" : "muted"}>{entry.definition ?? "Sin definición todavía."}</p>
            {entry.validated_by && <p className="muted small">Revisado por {entry.validated_by}</p>}
            {entry.estado === "candidato" && (
              <button className="btn secondary small" onClick={() => setEditing(entry)}>Revisar</button>
            )}
          </div>
        ))}
        {visible.length === 0 && !error && <p className="muted">No hay términos con esos filtros.</p>}
      </div>

      {editing && (
        <ValidateDialog
          entry={editing}
          user={user}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); refresh(); }}
        />
      )}
    </section>
  );
}

function ValidateDialog({ entry, user, onClose, onDone }: {
  entry: GlossaryEntry; user: User; onClose: () => void; onDone: () => void;
}) {
  const [definition, setDefinition] = useState(entry.definition ?? "");
  const [ambito, setAmbito] = useState<Ambito | "">(entry.ambito ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(estado: "validado" | "rechazado", event?: FormEvent) {
    event?.preventDefault();
    if (estado === "validado" && (!definition.trim() || !ambito)) {
      setError("Para validar se necesita una definición y un ámbito.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.validateEntry(entry.id, {
        estado,
        validated_by: user.display_name,
        definition: definition.trim() || undefined,
        ambito: ambito || undefined,
      });
      onDone();
    } catch (e) {
      const err = e as { status?: number; message: string };
      setError(err.status === 409 ? "Ese término ya tiene una entrada en ese ámbito." : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <form className="dialog" onClick={(e) => e.stopPropagation()} onSubmit={(e) => submit("validado", e)}>
        <h3>Revisar «{entry.term}»</h3>
        <label>Ámbito</label>
        <select value={ambito} onChange={(e) => setAmbito(e.target.value as Ambito | "")}>
          <option value="">Elige un ámbito…</option>
          {AMBITOS.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <label>Definición</label>
        <textarea rows={4} maxLength={1000} value={definition} onChange={(e) => setDefinition(e.target.value)}
          placeholder="Explica el término en lenguaje simple…" />
        {error && <p className="error small">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancelar</button>
          <button type="button" className="btn danger" disabled={busy} onClick={() => submit("rechazado")}>Rechazar</button>
          <button className="btn primary" disabled={busy}>Validar</button>
        </div>
      </form>
    </div>
  );
}
