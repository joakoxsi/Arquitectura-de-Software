// Cliente del API Gateway. La interfaz no conoce ningún otro servicio.

export interface User { id: string; display_name: string }
export interface Channel { id: string; name: string }
export interface Message {
  id: string;
  channel_id: string;
  author_id: string;
  author_name: string | null;
  content: string;
  created_at: string;
}

export type AudienceLevel = "basico" | "intermedio" | "experto";
export type Ambito =
  | "software" | "datos" | "producto" | "finanzas"
  | "marketing" | "operaciones" | "dominio";
export type Estado = "candidato" | "validado" | "rechazado";

export const AMBITOS: Ambito[] = [
  "software", "datos", "producto", "finanzas", "marketing", "operaciones", "dominio",
];
export const LEVELS: AudienceLevel[] = ["basico", "intermedio", "experto"];

export interface Meaning { definition?: string; ambito?: Ambito; [k: string]: unknown }
export interface TranslatedTerm {
  term: string;
  known: boolean;
  ambiguous: boolean;
  meanings: Meaning[];
}
export interface Translation {
  translation_id: string;
  message_id: string;
  audience_level: AudienceLevel;
  explanation: string;
  terms: TranslatedTerm[];
}
export interface GlossaryEntry {
  id: string;
  term: string;
  definition: string | null;
  ambito: Ambito | null;
  estado: Estado;
  created_at: string;
  validated_by: string | null;
  validated_at: string | null;
}

export interface SearchHit {
  id: string;
  channel_id: string;
  channel_name: string | null;
  author_id: string;
  author_name: string | null;
  content: string;
  created_at: string;
  has: string[];
  highlights: string[];
}
export interface SearchResult { total_results: number; messages: SearchHit[] }
export interface SearchParams {
  content?: string;
  channel_id?: string;
  author_id?: string;
  has?: ("link" | "mention")[];
  min_date?: string;
  max_date?: string;
  sort_by?: "timestamp" | "relevance";
  sort_order?: "desc" | "asc";
  limit?: number;
  offset?: number;
}
export type SummaryState = "pendiente" | "procesando" | "completada" | "fallida";
export interface TimeInterval { start: string; end: string }
export interface StructuredSummary {
  overview: string;
  decisions: string[];
  events: { description: string; when?: string | null }[];
  tasks: { description: string; assignee?: string | null }[];
}
export interface Summary {
  id: string;
  channel_id: string;
  requested_by: string | null;
  messageState: SummaryState;
  timeInterval: TimeInterval | null;
  content: string | null;
  structured: StructuredSummary | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

/** 202 del servicio de búsqueda: el índice aún se está construyendo. */
export class IndexNotReady extends Error {}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "No se pudo contactar al API Gateway");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch { /* respuesta sin JSON */ }
    throw new ApiError(response.status, detail);
  }
  // Solo la búsqueda usa 202 como "aún no"; en resúmenes 202 es "solicitud aceptada".
  if (response.status === 202 && path.includes("search")) throw new IndexNotReady("Índice en construcción");
  return response.json() as Promise<T>;
}

function searchQuery(p: SearchParams): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(p)) {
    if (key === "channel_id" || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => q.append(key, v));
    else q.append(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const qs = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params).filter(([, v]) => v) as [string, string][];
  return entries.length ? `?${new URLSearchParams(entries)}` : "";
};

export const api = {
  health: () => request<Record<string, string>>("GET", "/health"),

  createUser: (display_name: string) => request<User>("POST", "/users", { display_name }),
  getUser: (id: string) => request<User>("GET", `/users/${id}`),

  listChannels: () => request<Channel[]>("GET", "/channels"),
  createChannel: (name: string) => request<Channel>("POST", "/channels", { name }),

  listMessages: (channelId: string) =>
    request<Message[]>("GET", `/channels/${channelId}/messages`),
  sendMessage: (channelId: string, author_id: string, content: string) =>
    request<Message>("POST", `/channels/${channelId}/messages`, { author_id, content }),

  translate: (messageId: string, channelId: string, audience_level: AudienceLevel) =>
    request<Translation>(
      "POST",
      `/messages/${messageId}/translation${qs({ channel_id: channelId })}`,
      { audience_level },
    ),

  // Un canal usa la ruta por canal (el servicio enruta al shard de ese canal).
  searchMessages: (p: SearchParams) =>
    request<SearchResult>(
      "GET",
      p.channel_id
        ? `/channels/${p.channel_id}/messages/search${searchQuery(p)}`
        : `/search/messages${searchQuery(p)}`,
    ),

  requestSummary: (channelId: string, body: { user_id?: string; timeInterval?: TimeInterval }) =>
    request<{ summary_id: string; messageState: SummaryState }>(
      "POST", `/channels/${channelId}/summaries`, body),
  getSummary: (summaryId: string) => request<Summary>("GET", `/summaries/${summaryId}`),
  listSummaries: (channelId: string) =>
    request<Summary[]>("GET", `/channels/${channelId}/summaries?limit=20`),

  listGlossary: (ambito?: Ambito, estado?: Estado) =>
    request<GlossaryEntry[]>("GET", `/glossary${qs({ ambito, estado })}`),
  validateEntry: (
    entryId: string,
    body: { estado: "validado" | "rechazado"; validated_by: string; definition?: string; ambito?: Ambito },
  ) => request<GlossaryEntry>("PATCH", `/glossary/${entryId}/validation`, body),
};
