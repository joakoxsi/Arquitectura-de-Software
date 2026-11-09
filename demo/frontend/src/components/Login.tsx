import { FormEvent, useState } from "react";
import { api, User } from "../api";

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = value.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const user = mode === "new" ? await api.createUser(text) : await api.getUser(text);
      onLogin(user);
    } catch (e) {
      const err = e as { status?: number; message: string };
      setError(err.status === 404 ? "No existe un usuario con ese id." : err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="login-card">
        <div className="brand">
          <span className="brand-mark">C</span>
          <div>
            <h1>Chat Microsvcs</h1>
            <p>Arquitectura de Software · USM</p>
          </div>
        </div>

        <div className="tabs">
          <button className={mode === "new" ? "active" : ""} onClick={() => { setMode("new"); setValue(""); setError(null); }}>
            Soy nuevo
          </button>
          <button className={mode === "existing" ? "active" : ""} onClick={() => { setMode("existing"); setValue(""); setError(null); }}>
            Ya tengo id
          </button>
        </div>

        <form onSubmit={submit}>
          <label htmlFor="login-input">{mode === "new" ? "¿Cómo te llamas?" : "Tu id de usuario"}</label>
          <input
            id="login-input"
            autoFocus
            maxLength={mode === "new" ? 80 : undefined}
            placeholder={mode === "new" ? "Ej. Joaquín" : "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <button className="btn primary block" disabled={busy || !value.trim()}>
            {busy ? "Entrando…" : mode === "new" ? "Crear usuario y entrar" : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
