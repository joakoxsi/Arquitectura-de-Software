"""Esquema GraphQL del Gateway: queries y mutaciones sobre todos los servicios.

La interfaz web usa esta API (POST /graphql). Cada resolver llama al servicio
dueño del dato por su API pública (ver app/services.py). Los errores de un
servicio llegan como errores GraphQL con `extensions: {code, status}`.
"""
from enum import Enum
from typing import Optional

import strawberry

from app import services as svc
from app.services import (CHANNELS_URL, OZY_URL, SUMMARIES_URL, USERS_URL)

# --- Enums (los valores son los mismos que usan los servicios) ---------------


@strawberry.enum(description="Nivel de detalle de la explicación de Ozy.")
class AudienceLevel(Enum):
    basico = "basico"
    intermedio = "intermedio"
    experto = "experto"


@strawberry.enum(description="Contexto donde una definición del glosario es válida.")
class Ambito(Enum):
    software = "software"
    datos = "datos"
    producto = "producto"
    finanzas = "finanzas"
    marketing = "marketing"
    operaciones = "operaciones"
    dominio = "dominio"


@strawberry.enum(description="Estado de una entrada del glosario.")
class Estado(Enum):
    candidato = "candidato"
    validado = "validado"
    rechazado = "rechazado"


@strawberry.enum(description="Resultado de revisar una entrada del glosario.")
class Decision(Enum):
    validado = "validado"
    rechazado = "rechazado"


@strawberry.enum(description="Tipo de contenido que debe tener un mensaje buscado.")
class HasFilter(Enum):
    link = "link"
    mention = "mention"


@strawberry.enum
class SortBy(Enum):
    timestamp = "timestamp"
    relevance = "relevance"


@strawberry.enum
class SortOrder(Enum):
    desc = "desc"
    asc = "asc"


def _enum(enum: type[Enum], value: str | None):
    return enum(value) if value else None


# --- Usuarios, canales y mensajes --------------------------------------------


@strawberry.type(description="Integrante del chat (servicio users).")
class User:
    id: strawberry.ID
    display_name: str

    @staticmethod
    def of(data: dict) -> "User":
        return User(id=data["id"], display_name=data["display_name"])


@strawberry.type(description="Mensaje de un canal (servicio messages).")
class Message:
    id: strawberry.ID
    channel_id: str
    author_id: str
    author_name: Optional[str]
    content: str
    created_at: str

    @strawberry.field(description="Autor completo, consultado al servicio users.")
    async def author(self) -> Optional[User]:
        name = await svc.display_name(self.author_id)
        return User(id=self.author_id, display_name=name) if name is not None else None

    @strawberry.field(description="Explicación de Ozy ya generada para este mensaje.")
    async def translation(self, audience_level: AudienceLevel = AudienceLevel.basico
                          ) -> Optional["Translation"]:
        try:
            return await _get_translation(self.id, audience_level)
        except svc.ServiceError as error:
            if error.status == 404:
                return None
            raise

    @staticmethod
    def of(data: dict) -> "Message":
        return Message(id=data["id"], channel_id=data["channel_id"],
                       author_id=data["author_id"], author_name=data.get("author_name"),
                       content=data["content"], created_at=data.get("created_at", ""))


@strawberry.type(description="Canal del chat (servicio channels).")
class Channel:
    id: strawberry.ID
    name: str

    @strawberry.field(description="Mensajes del canal en orden cronológico (servicio messages).")
    async def messages(self) -> list[Message]:
        return [Message.of(m) for m in await svc.list_messages(self.id)]

    @staticmethod
    def of(data: dict) -> "Channel":
        return Channel(id=data["id"], name=data["name"])


# --- Ozy: traducciones y glosario --------------------------------------------


@strawberry.type(description="Un significado posible de un término detectado.")
class Meaning:
    entry_id: str
    ambito: Optional[Ambito]
    definition: Optional[str]
    estado: Estado


@strawberry.type(description="Término técnico detectado en un mensaje.")
class TranslatedTerm:
    term: str
    known: bool
    ambiguous: bool
    meanings: list[Meaning]


@strawberry.type(description="Explicación en simple de un mensaje (servicio Ozy).")
class Translation:
    translation_id: strawberry.ID
    message_id: str
    channel_id: str
    audience_level: AudienceLevel
    explanation: str
    terms: list[TranslatedTerm]
    created_at: str
    author: Optional[User] = None

    @staticmethod
    def of(data: dict) -> "Translation":
        author = data.get("author") or {}
        return Translation(
            translation_id=data["translation_id"], message_id=data["message_id"],
            channel_id=data["channel_id"],
            audience_level=AudienceLevel(data["audience_level"]),
            explanation=data["explanation"], created_at=data.get("created_at", ""),
            terms=[TranslatedTerm(
                term=t["term"], known=t["known"], ambiguous=t["ambiguous"],
                meanings=[Meaning(entry_id=m["entry_id"], ambito=_enum(Ambito, m.get("ambito")),
                                  definition=m.get("definition"), estado=Estado(m["estado"]))
                          for m in t["meanings"]])
                for t in data["terms"]],
            author=(User(id=author["id"], display_name=author["display_name"])
                    if author.get("id") and author.get("display_name") else None))


@strawberry.type(description="Entrada del glosario: un término con una definición en un ámbito.")
class GlossaryEntry:
    id: strawberry.ID
    term: str
    definition: Optional[str]
    ambito: Optional[Ambito]
    estado: Estado
    created_at: str
    validated_by: Optional[str]
    validated_at: Optional[str]

    @staticmethod
    def of(data: dict) -> "GlossaryEntry":
        return GlossaryEntry(
            id=data["id"], term=data["term"], definition=data.get("definition"),
            ambito=_enum(Ambito, data.get("ambito")), estado=Estado(data["estado"]),
            created_at=data.get("created_at", ""), validated_by=data.get("validated_by"),
            validated_at=data.get("validated_at"))


@strawberry.type(description="Todas las entradas de un término, por ámbito.")
class TermDetail:
    term: str
    ambiguous: bool
    entries: list[GlossaryEntry]


async def _get_translation(message_id: str, level: AudienceLevel) -> Translation:
    data = await svc.call("GET", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
                          params={"audience_level": level.value})
    return Translation.of(data)


# --- Búsqueda -----------------------------------------------------------------


@strawberry.type(description="Mensaje encontrado por la búsqueda (servicio search).")
class SearchHit:
    id: strawberry.ID
    channel_id: str
    channel_name: Optional[str]
    author_id: str
    author_name: Optional[str]
    content: str
    created_at: str
    has: list[str]
    mentions: list[str]
    links: list[str]
    highlights: list[str]


@strawberry.type(description="Resultado de una búsqueda. `ready` es falso mientras el "
                             "servicio aún construye su índice: reintentar en `retryAfter` s.")
class SearchResult:
    ready: bool
    retry_after: Optional[int]
    total_results: int
    messages: list[SearchHit]


# --- Resúmenes ----------------------------------------------------------------


@strawberry.type
class TimeInterval:
    start: str
    end: str


@strawberry.input(description="Rango de fechas en ISO 8601.")
class TimeIntervalInput:
    start: str
    end: str


@strawberry.type
class SummaryEvent:
    description: str
    when: Optional[str]


@strawberry.type
class SummaryTask:
    description: str
    assignee: Optional[str]


@strawberry.type(description="Resumen estructurado generado por el LLM.")
class StructuredSummary:
    overview: str
    decisions: list[str]
    events: list[SummaryEvent]
    tasks: list[SummaryTask]


@strawberry.type(description="Resumen de un canal (servicio summaries). `messageState` es "
                             "pendiente, procesando, completada o fallida.")
class Summary:
    id: strawberry.ID
    channel_id: str
    requested_by: Optional[str]
    message_state: str
    time_interval: Optional[TimeInterval]
    content: Optional[str]
    structured: Optional[StructuredSummary]
    error: Optional[str]
    created_at: str
    updated_at: str

    @staticmethod
    def of(data: dict) -> "Summary":
        interval = data.get("timeInterval")
        s = data.get("structured")
        return Summary(
            id=data["id"], channel_id=data["channel_id"], requested_by=data.get("requested_by"),
            message_state=data["messageState"],
            time_interval=TimeInterval(start=interval["start"], end=interval["end"])
            if interval else None,
            content=data.get("content"), error=data.get("error"),
            created_at=data.get("created_at", ""), updated_at=data.get("updated_at", ""),
            structured=StructuredSummary(
                overview=s.get("overview", ""), decisions=s.get("decisions", []),
                events=[SummaryEvent(description=e["description"], when=e.get("when"))
                        for e in s.get("events", [])],
                tasks=[SummaryTask(description=t["description"], assignee=t.get("assignee"))
                       for t in s.get("tasks", [])]) if s else None)


@strawberry.type(description="Solicitud de resumen aceptada; consultar `summary(id)` hasta terminar.")
class SummaryRequest:
    summary_id: strawberry.ID
    message_state: str


@strawberry.type
class ServiceStatus:
    service: str
    status: str


# --- Raíz ---------------------------------------------------------------------


@strawberry.type
class Query:
    @strawberry.field(description="Estado de cada microservicio detrás del Gateway.")
    async def health(self) -> list[ServiceStatus]:
        return [ServiceStatus(service=name, status=status)
                for name, status in (await svc.services_health()).items()]

    @strawberry.field
    async def user(self, id: strawberry.ID) -> User:
        return User.of(svc.remember(await svc.call("GET", f"{USERS_URL}/api/v1/users/{id}")))

    @strawberry.field
    async def channels(self) -> list[Channel]:
        return [Channel.of(c) for c in await svc.call("GET", f"{CHANNELS_URL}/api/v1/channels")]

    @strawberry.field
    async def channel(self, id: strawberry.ID) -> Channel:
        return Channel.of(await svc.call("GET", f"{CHANNELS_URL}/api/v1/channels/{id}"))

    @strawberry.field(description="Mensajes del canal en orden cronológico, con su autor.")
    async def messages(self, channel_id: strawberry.ID) -> list[Message]:
        return [Message.of(m) for m in await svc.list_messages(channel_id)]

    @strawberry.field(description="Explicación guardada de un mensaje (botón «Explícamelo en simple»).")
    async def translation(self, message_id: strawberry.ID,
                          audience_level: AudienceLevel = AudienceLevel.basico) -> Translation:
        return await _get_translation(message_id, audience_level)

    @strawberry.field(description="Glosario de Ozy, con filtros opcionales.")
    async def glossary(self, ambito: Optional[Ambito] = None,
                       estado: Optional[Estado] = None) -> list[GlossaryEntry]:
        params = {k: v.value for k, v in {"ambito": ambito, "estado": estado}.items() if v}
        return [GlossaryEntry.of(e)
                for e in await svc.call("GET", f"{OZY_URL}/api/v1/glossary", params=params)]

    @strawberry.field(description="Todas las entradas de un término (ej. PR tiene 3 ámbitos).")
    async def term(self, term: str) -> TermDetail:
        data = await svc.call("GET", f"{OZY_URL}/api/v1/glossary/{term}")
        return TermDetail(term=data["term"], ambiguous=data["ambiguous"],
                          entries=[GlossaryEntry.of(e) for e in data["entries"]])

    @strawberry.field(description="Búsqueda de mensajes (servicio search). `mentions` filtra "
                                  "por usuarios mencionados con <@id>; `limit` máximo 25.")
    async def search_messages(
            self, content: Optional[str] = None, channel_id: Optional[strawberry.ID] = None,
            author_ids: Optional[list[strawberry.ID]] = None,
            mentions: Optional[list[strawberry.ID]] = None,
            has: Optional[list[HasFilter]] = None, min_date: Optional[str] = None,
            max_date: Optional[str] = None, sort_by: Optional[SortBy] = None,
            sort_order: Optional[SortOrder] = None, limit: Optional[int] = None,
            offset: Optional[int] = None) -> SearchResult:
        params: list[tuple[str, str]] = []
        for key, value in [("content", content), ("min_date", min_date),
                           ("max_date", max_date), ("limit", limit), ("offset", offset),
                           ("sort_by", sort_by and sort_by.value),
                           ("sort_order", sort_order and sort_order.value)]:
            if value not in (None, ""):
                params.append((key, str(value)))
        params += [("author_id", a) for a in author_ids or []]
        params += [("mentions", m) for m in mentions or []]
        params += [("has", h.value) for h in has or []]
        status, data = await svc.search(svc.search_path(channel_id), params)
        if status == 202:
            return SearchResult(ready=False, retry_after=data.get("retry_after"),
                                total_results=0, messages=[])
        return SearchResult(
            ready=True, retry_after=None, total_results=data.get("total_results", 0),
            messages=[SearchHit(
                id=m["id"], channel_id=m["channel_id"], channel_name=m.get("channel_name"),
                author_id=m["author_id"], author_name=m.get("author_name"),
                content=m["content"], created_at=m.get("created_at", ""),
                has=m.get("has", []), mentions=m.get("mentions", []),
                links=m.get("links", []), highlights=m.get("highlights", []))
                for m in data.get("messages", [])])

    @strawberry.field
    async def summaries(self, channel_id: strawberry.ID, limit: int = 20,
                        offset: int = 0) -> list[Summary]:
        data = await svc.call("GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                              params={"limit": limit, "offset": offset})
        return [Summary.of(s) for s in data]

    @strawberry.field
    async def latest_summary(self, channel_id: strawberry.ID) -> Optional[Summary]:
        """Último resumen completado, o null si el canal aún no tiene ninguno."""
        try:
            data = await svc.call(
                "GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries/latest")
        except svc.ServiceError as error:
            # summaries responde 404 tanto si no hay resumen completado como si el
            # canal no existe: ambos casos son «no hay último resumen» para la interfaz.
            if error.status == 404:
                return None
            raise
        return Summary.of(data)

    @strawberry.field
    async def summary(self, id: strawberry.ID) -> Summary:
        return Summary.of(await svc.call("GET", f"{SUMMARIES_URL}/api/v1/summaries/{id}"))


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_user(self, display_name: str) -> User:
        user = await svc.call("POST", f"{USERS_URL}/api/v1/users",
                              json={"display_name": display_name})
        return User.of(svc.remember(user))

    @strawberry.mutation
    async def create_channel(self, name: str) -> Channel:
        return Channel.of(await svc.call("POST", f"{CHANNELS_URL}/api/v1/channels",
                                         json={"name": name}))

    @strawberry.mutation(description="Publica un mensaje; messages emite chat.message.created.")
    async def send_message(self, channel_id: strawberry.ID, author_id: strawberry.ID,
                           content: str) -> Message:
        return Message.of(await svc.create_message(
            channel_id, {"author_id": author_id, "content": content}))

    @strawberry.mutation(description="Pide a Ozy la explicación en simple de un mensaje.")
    async def translate_message(self, message_id: strawberry.ID,
                                audience_level: AudienceLevel = AudienceLevel.basico,
                                channel_id: Optional[strawberry.ID] = None) -> Translation:
        data = await svc.call(
            "POST", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
            params={"channel_id": channel_id} if channel_id else None,
            json={"audience_level": audience_level.value})
        return Translation.of(data)

    @strawberry.mutation(description="Valida o rechaza una definición; un candidato se "
                                     "completa enviando definición y ámbito.")
    async def validate_glossary_entry(
            self, entry_id: strawberry.ID, estado: Decision, validated_by: strawberry.ID,
            definition: Optional[str] = None, ambito: Optional[Ambito] = None) -> GlossaryEntry:
        body = {"estado": estado.value, "validated_by": validated_by}
        if definition is not None:
            body["definition"] = definition
        if ambito is not None:
            body["ambito"] = ambito.value
        return GlossaryEntry.of(await svc.call(
            "PATCH", f"{OZY_URL}/api/v1/glossary/{entry_id}/validation", json=body))

    @strawberry.mutation(description="Pide un resumen del canal. Sin rango: lo nuevo del canal.")
    async def request_summary(self, channel_id: strawberry.ID,
                              user_id: Optional[strawberry.ID] = None,
                              time_interval: Optional[TimeIntervalInput] = None
                              ) -> SummaryRequest:
        body: dict = {}
        if user_id:
            body["user_id"] = user_id
        if time_interval:
            body["timeInterval"] = {"start": time_interval.start, "end": time_interval.end}
        data = await svc.call("POST", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                              json=body)  # siempre un objeto JSON, aunque sea {}
        return SummaryRequest(summary_id=data["summary_id"], message_state=data["messageState"])


schema = strawberry.Schema(query=Query, mutation=Mutation)
