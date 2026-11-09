// Cliente del API Gateway (GraphQL en /graphql). La interfaz no conoce ningún otro servicio.
// Las consultas usan alias (`display_name: displayName`) para que las respuestas tengan la
// misma forma que los tipos de abajo.

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

/** La búsqueda aún construye su índice (`ready: false`): reintentar más tarde. */
export class IndexNotReady extends Error {}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

interface GraphQLError { message: string; extensions?: { status?: number; code?: string } }

/** Ejecuta una operación GraphQL. Un error de un servicio llega con su código HTTP en
 *  `extensions.status` (ej. 404), que se conserva en ApiError.status. */
async function gql<T>(query: string, variables?: Record<string, unknown>): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/graphql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });
  } catch {
    throw new ApiError(0, "No se pudo contactar al API Gateway");
  }
  let payload: { data?: T; errors?: GraphQLError[] };
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(response.status, response.statusText || "Respuesta inválida del Gateway");
  }
  if (payload.errors?.length) {
    const [error] = payload.errors;
    throw new ApiError(error.extensions?.status ?? 400, error.message);
  }
  if (!response.ok || !payload.data) throw new ApiError(response.status, response.statusText);
  return payload.data;
}

const USER = "id display_name: displayName";
const MESSAGE = `id channel_id: channelId author_id: authorId author_name: authorName
  content created_at: createdAt`;
const TRANSLATION = `translation_id: translationId message_id: messageId
  audience_level: audienceLevel explanation
  terms { term known ambiguous meanings { entry_id: entryId ambito definition estado } }`;
const ENTRY = `id term definition ambito estado created_at: createdAt
  validated_by: validatedBy validated_at: validatedAt`;
const HIT = `id channel_id: channelId channel_name: channelName author_id: authorId
  author_name: authorName content created_at: createdAt has highlights`;
const SUMMARY = `id channel_id: channelId requested_by: requestedBy messageState
  timeInterval { start end } content error created_at: createdAt updated_at: updatedAt
  structured { overview decisions events { description when } tasks { description assignee } }`;

export const api = {
  health: async () => {
    const data = await gql<{ health: { service: string; status: string }[] }>(
      "query Health { health { service status } }");
    return Object.fromEntries(data.health.map((s) => [s.service, s.status]));
  },

  createUser: async (displayName: string) =>
    (await gql<{ createUser: User }>(
      `mutation CreateUser($displayName: String!) { createUser(displayName: $displayName) { ${USER} } }`,
      { displayName })).createUser,
  getUser: async (id: string) =>
    (await gql<{ user: User }>(`query User($id: ID!) { user(id: $id) { ${USER} } }`, { id })).user,

  listChannels: async () =>
    (await gql<{ channels: Channel[] }>("query Channels { channels { id name } }")).channels,
  createChannel: async (name: string) =>
    (await gql<{ createChannel: Channel }>(
      "mutation CreateChannel($name: String!) { createChannel(name: $name) { id name } }",
      { name })).createChannel,

  listMessages: async (channelId: string) =>
    (await gql<{ messages: Message[] }>(
      `query Messages($channelId: ID!) { messages(channelId: $channelId) { ${MESSAGE} } }`,
      { channelId })).messages,
  sendMessage: async (channelId: string, authorId: string, content: string) =>
    (await gql<{ sendMessage: Message }>(
      `mutation SendMessage($channelId: ID!, $authorId: ID!, $content: String!) {
        sendMessage(channelId: $channelId, authorId: $authorId, content: $content) { ${MESSAGE} }
      }`, { channelId, authorId, content })).sendMessage,

  translate: async (messageId: string, channelId: string, audienceLevel: AudienceLevel) =>
    (await gql<{ translateMessage: Translation }>(
      `mutation Translate($messageId: ID!, $channelId: ID, $audienceLevel: AudienceLevel!) {
        translateMessage(messageId: $messageId, channelId: $channelId,
                         audienceLevel: $audienceLevel) { ${TRANSLATION} }
      }`, { messageId, channelId, audienceLevel })).translateMessage,

  searchMessages: async (p: SearchParams) => {
    const { searchMessages: result } = await gql<{
      searchMessages: SearchResult & { ready: boolean };
    }>(
      `query Search($content: String, $channelId: ID, $authorIds: [ID!], $has: [HasFilter!],
                    $minDate: String, $maxDate: String, $sortBy: SortBy, $sortOrder: SortOrder,
                    $limit: Int, $offset: Int) {
        searchMessages(content: $content, channelId: $channelId, authorIds: $authorIds,
                       has: $has, minDate: $minDate, maxDate: $maxDate, sortBy: $sortBy,
                       sortOrder: $sortOrder, limit: $limit, offset: $offset) {
          ready total_results: totalResults messages { ${HIT} }
        }
      }`,
      {
        content: p.content || undefined, channelId: p.channel_id,
        authorIds: p.author_id ? [p.author_id] : undefined, has: p.has,
        minDate: p.min_date, maxDate: p.max_date, sortBy: p.sort_by, sortOrder: p.sort_order,
        limit: p.limit, offset: p.offset,
      });
    if (!result.ready) throw new IndexNotReady("Índice en construcción");
    return result as SearchResult;
  },

  requestSummary: async (channelId: string, body: { user_id?: string; timeInterval?: TimeInterval }) =>
    (await gql<{ requestSummary: { summary_id: string; messageState: SummaryState } }>(
      `mutation RequestSummary($channelId: ID!, $userId: ID, $timeInterval: TimeIntervalInput) {
        requestSummary(channelId: $channelId, userId: $userId, timeInterval: $timeInterval) {
          summary_id: summaryId messageState
        }
      }`, { channelId, userId: body.user_id, timeInterval: body.timeInterval })).requestSummary,
  getSummary: async (summaryId: string) =>
    (await gql<{ summary: Summary }>(
      `query Summary($id: ID!) { summary(id: $id) { ${SUMMARY} } }`, { id: summaryId })).summary,
  listSummaries: async (channelId: string) =>
    (await gql<{ summaries: Summary[] }>(
      `query Summaries($channelId: ID!) { summaries(channelId: $channelId, limit: 20) { ${SUMMARY} } }`,
      { channelId })).summaries,

  listGlossary: async (ambito?: Ambito, estado?: Estado) =>
    (await gql<{ glossary: GlossaryEntry[] }>(
      `query Glossary($ambito: Ambito, $estado: Estado) {
        glossary(ambito: $ambito, estado: $estado) { ${ENTRY} }
      }`, { ambito, estado })).glossary,
  validateEntry: async (
    entryId: string,
    body: { estado: "validado" | "rechazado"; validated_by: string; definition?: string; ambito?: Ambito },
  ) =>
    (await gql<{ validateGlossaryEntry: GlossaryEntry }>(
      `mutation Validate($entryId: ID!, $estado: Decision!, $validatedBy: ID!,
                         $definition: String, $ambito: Ambito) {
        validateGlossaryEntry(entryId: $entryId, estado: $estado, validatedBy: $validatedBy,
                              definition: $definition, ambito: $ambito) { ${ENTRY} }
      }`, { entryId, estado: body.estado, validatedBy: body.validated_by,
            definition: body.definition, ambito: body.ambito })).validateGlossaryEntry,
};
