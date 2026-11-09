"""Acceso a los microservicios: lo comparten la API GraphQL y la API REST.

El Gateway no guarda estado propio salvo una caché de nombres. Cada llamada va al
microservicio dueño del dato por su API pública.
"""
import asyncio
import os
from typing import Any

import httpx

USERS_URL = os.environ.get("USERS_URL", "http://users:8000")
CHANNELS_URL = os.environ.get("CHANNELS_URL", "http://channels:8000")
MESSAGES_URL = os.environ.get("MESSAGES_URL", "http://messages:8000")
OZY_URL = os.environ.get("OZY_URL", "http://ozy:8000")
# Búsqueda (capacidad de otro grupo, Elasticsearch). En el clúster se llega por su
# Ingress: la NetworkPolicy del curso no deja entrar tráfico desde otros namespaces.
# Mientras su Ingress no tenga DNS real, SEARCH_HOST manda el Host que espera Traefik.
SEARCH_URL = os.environ.get("SEARCH_URL", "http://search:8000")
SEARCH_HOST = os.environ.get("SEARCH_HOST") or None
SEARCH_HEADERS = {"Host": SEARCH_HOST} if SEARCH_HOST else {}
# Resúmenes con LLM (capacidad de otro grupo). Asíncrono: POST → 202 + id, luego polling.
SUMMARIES_URL = os.environ.get("SUMMARIES_URL", "http://summaries:8000")

SERVICES = {"users": USERS_URL, "channels": CHANNELS_URL,
            "messages": MESSAGES_URL, "ozy": OZY_URL, "search": SEARCH_URL,
            "summaries": SUMMARIES_URL}

ERROR_CODES = {400: "BAD_REQUEST", 404: "NOT_FOUND", 409: "CONFLICT",
               422: "VALIDATION_ERROR", 503: "SERVICE_UNAVAILABLE"}

client = httpx.AsyncClient(timeout=5.0)
# Caché de nombres: los usuarios no cambian su display_name (no hay endpoint para ello).
display_names: dict[str, str] = {}


class ServiceError(Exception):
    """Error de un microservicio, con su código HTTP y detalle tal cual.

    `extensions` lo usa GraphQL: graphql-core copia este atributo al error que
    devuelve, así la interfaz recibe el mismo código que con REST.
    """

    def __init__(self, status: int, detail: Any):
        self.status = status
        self.detail = detail
        message = detail if isinstance(detail, str) else str(detail)
        super().__init__(message)
        self.extensions = {"code": ERROR_CODES.get(status, "SERVICE_ERROR"),
                           "status": status}


def _detail(response: httpx.Response) -> Any:
    try:
        return response.json().get("detail", response.text)
    except (ValueError, AttributeError):
        return response.text


async def call(method: str, url: str, **kwargs: Any) -> Any:
    """Llama a un servicio y propaga su código y detalle de error tal cual."""
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.RequestError:
        raise ServiceError(503, "Servicio no disponible")
    if response.status_code >= 400:
        raise ServiceError(response.status_code, _detail(response))
    return response.json()


async def services_health() -> dict[str, str]:
    async def check(url: str) -> str:
        headers = SEARCH_HEADERS if url == SEARCH_URL else None
        try:
            response = await client.get(f"{url}/health", timeout=2.0, headers=headers)
            return "ok" if response.status_code == 200 else "fail"
        except httpx.RequestError:
            return "down"
    results = await asyncio.gather(*(check(url) for url in SERVICES.values()))
    return dict(zip(SERVICES, results))


# --- Usuarios, canales y mensajes ------------------------------------------

def remember(user: dict) -> dict:
    display_names[user["id"]] = user["display_name"]
    return user


async def display_name(user_id: str) -> str | None:
    if user_id in display_names:
        return display_names[user_id]
    try:
        user = await call("GET", f"{USERS_URL}/api/v1/users/{user_id}")
    except ServiceError:
        return None
    return remember(user)["display_name"]


async def author_names(user_ids: set[str]) -> dict[str, str | None]:
    names = await asyncio.gather(*(display_name(user_id) for user_id in user_ids))
    return dict(zip(user_ids, names))


async def channel_names() -> dict[str, str]:
    try:
        channels = await call("GET", f"{CHANNELS_URL}/api/v1/channels")
    except ServiceError:
        return {}
    return {c["id"]: c["name"] for c in channels}


async def list_messages(channel_id: str) -> list[dict]:
    """Mensajes del canal en orden cronológico, con el nombre del autor."""
    messages = await call("GET", f"{MESSAGES_URL}/api/v1/channels/{channel_id}/messages")
    names = await author_names({m["author_id"] for m in messages})
    messages.sort(key=lambda m: m.get("created_at", ""))
    return [{**m, "author_name": names.get(m["author_id"])} for m in messages]


async def create_message(channel_id: str, body: Any) -> dict:
    message = await call("POST", f"{MESSAGES_URL}/api/v1/channels/{channel_id}/messages",
                         json=body)
    return {**message, "author_name": await display_name(message["author_id"])}


# --- Búsqueda (Elasticsearch, servicio "search") ---------------------------

async def search(path: str, params: list[tuple[str, str]]) -> tuple[int, dict]:
    """Reenvía la búsqueda con sus filtros (los repetibles, como author_id, tal cual)
    y agrega nombres de autor y canal a cada resultado.

    Devuelve (202, cuerpo) mientras el índice se construye, y (200, resultado) al final.
    """
    try:
        response = await client.get(f"{SEARCH_URL}{path}", headers=SEARCH_HEADERS,
                                    params=params)
    except httpx.RequestError:
        raise ServiceError(503, "Búsqueda no disponible")
    if response.status_code == 202:  # índice aún construyéndose: se reintenta
        body = response.json()
        body.setdefault("retry_after", int(response.headers.get("Retry-After", "2")))
        return 202, body
    if response.status_code >= 400:
        raise ServiceError(response.status_code, _detail(response))
    result = response.json()
    messages = result.get("messages", [])
    names, channels = await asyncio.gather(
        author_names({m["author_id"] for m in messages}), channel_names())
    result["messages"] = [{**m, "author_name": names.get(m["author_id"]),
                           "channel_name": channels.get(m["channel_id"])}
                          for m in messages]
    return 200, result


def search_path(channel_id: str | None) -> str:
    # Un canal usa la ruta por canal (el servicio enruta al shard de ese canal).
    if channel_id:
        return f"/api/v1/channels/{channel_id}/messages/search"
    return "/api/v1/search/messages"
