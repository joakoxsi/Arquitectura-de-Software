import { useEffect, useState } from "react";
import { api, Channel, User } from "./api";
import Login from "./components/Login";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import GlossaryView from "./components/GlossaryView";
import SearchView from "./components/SearchView";

const USER_KEY = "chat.user";

type View =
  | { kind: "channel"; channel: Channel }
  | { kind: "glossary" }
  | { kind: "search"; channelId?: string }
  | { kind: "empty" };

function loadUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [user, setUser] = useState<User | null>(loadUser);
  const [view, setView] = useState<View>({ kind: "empty" });

  // Confirma que el usuario guardado sigue existiendo en el servicio users.
  useEffect(() => {
    if (!user) return;
    api.getUser(user.id).catch((error) => {
      if (error.status === 404) logout();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function login(next: User) {
    try { localStorage.setItem(USER_KEY, JSON.stringify(next)); } catch { /* sin storage */ }
    setUser(next);
  }

  function logout() {
    try { localStorage.removeItem(USER_KEY); } catch { /* sin storage */ }
    setUser(null);
    setView({ kind: "empty" });
  }

  if (!user) return <Login onLogin={login} />;

  return (
    <div className="app">
      <Sidebar
        user={user}
        activeChannelId={view.kind === "channel" ? view.channel.id : null}
        glossaryActive={view.kind === "glossary"}
        searchActive={view.kind === "search"}
        onSelectChannel={(channel) => setView({ kind: "channel", channel })}
        onOpenGlossary={() => setView({ kind: "glossary" })}
        onOpenSearch={() => setView({ kind: "search" })}
        onLogout={logout}
      />
      <main className="main">
        {view.kind === "channel" && (
          <ChatView
            key={view.channel.id}
            channel={view.channel}
            user={user}
            onSearch={() => setView({ kind: "search", channelId: view.channel.id })}
          />
        )}
        {view.kind === "search" && (
          <SearchView
            key={view.channelId ?? "all"}
            user={user}
            initialChannelId={view.channelId}
            onOpenChannel={(channel) => setView({ kind: "channel", channel })}
          />
        )}
        {view.kind === "glossary" && <GlossaryView user={user} />}
        {view.kind === "empty" && (
          <div className="empty-state">
            <div className="empty-icon">#</div>
            <h2>Hola, {user.display_name}</h2>
            <p>Elige un canal de la izquierda o crea uno nuevo para empezar a conversar.</p>
          </div>
        )}
      </main>
    </div>
  );
}
