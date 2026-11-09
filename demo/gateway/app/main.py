"""API Gateway: único punto de entrada de la interfaz web.

La interfaz solo conoce este servicio. El Gateway reenvía cada petición al
microservicio dueño del dato (users, channels, messages, ozy, search, summaries) usando sus APIs
públicas y, cuando ayuda a la interfaz, combina respuestas (ej. agrega el nombre
del autor a cada mensaje). No guarda estado propio salvo una caché de nombres.
"""
import asyncio
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

SERVICES = {"users": USERS_URL, "channels": CHANNELS_URL,
            "messages": MESSAGES_URL, "ozy": OZY_URL, "search": SEARCH_URL,
            "summaries": SUMMARIES_URL}

app = FastAPI(title="Chat API Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])

client = httpx.AsyncClient(timeout=5.0)
# Caché de nombres: los usuarios no cambian su display_name (no hay endpoint para ello).
display_names: dict[str, str] = {}


@app.on_event("shutdown")
async def close_client() -> None:
    await client.aclose()


async def forward(method: str, url: str, **kwargs: Any) -> Any:
    """Llama a un servicio y propaga su código y detalle de error tal cual."""
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Servicio no disponible")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    return response.json()


async def json_body(request: Request) -> Any:
    """Cuerpo JSON de la petición; 400 si no es JSON válido en UTF-8."""
    try:
        return await request.json()
    except ValueError:  # incluye JSONDecodeError y UnicodeDecodeError
        raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON válido (UTF-8)")


async def display_name(user_id: str) -> str | None:
    if user_id in display_names:
        return display_names[user_id]
    try:
        user = await forward("GET", f"{USERS_URL}/api/v1/users/{user_id}")
    except HTTPException:
        return None
    display_names[user_id] = user["display_name"]
    return user["display_name"]


# --- Salud ----------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/health")
async def services_health():
    async def check(url: str) -> str:
        headers = SEARCH_HEADERS if url == SEARCH_URL else None
        try:
            response = await client.get(f"{url}/health", timeout=2.0, headers=headers)
            return "ok" if response.status_code == 200 else "fail"
        except httpx.RequestError:
            return "down"
    results = await asyncio.gather(*(check(url) for url in SERVICES.values()))
    return dict(zip(SERVICES, results))


# --- Usuarios -------------------------------------------------------------

@app.post("/api/users", status_code=201)
async def create_user(request: Request):
    user = await forward("POST", f"{USERS_URL}/api/v1/users", json=await json_body(request))
    display_names[user["id"]] = user["display_name"]
    return user


@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    user = await forward("GET", f"{USERS_URL}/api/v1/users/{user_id}")
    display_names[user["id"]] = user["display_name"]
    return user


# --- Canales --------------------------------------------------------------

@app.get("/api/channels")
async def list_channels():
    return await forward("GET", f"{CHANNELS_URL}/api/v1/channels")


@app.post("/api/channels", status_code=201)
async def create_channel(request: Request):
    return await forward("POST", f"{CHANNELS_URL}/api/v1/channels",
                         json=await json_body(request))


@app.get("/api/channels/{channel_id}")
async def get_channel(channel_id: str):
    return await forward("GET", f"{CHANNELS_URL}/api/v1/channels/{channel_id}")


# --- Mensajes (con nombre del autor) -------------------------------------

@app.get("/api/channels/{channel_id}/messages")
async def list_messages(channel_id: str):
    messages = await forward("GET", f"{MESSAGES_URL}/api/v1/channels/{channel_id}/messages")
    authors = {m["author_id"] for m in messages}
    names = dict(zip(authors, await asyncio.gather(*(display_name(a) for a in authors))))
    messages.sort(key=lambda m: m.get("created_at", ""))
    return [{**m, "author_name": names.get(m["author_id"])} for m in messages]


@app.post("/api/channels/{channel_id}/messages", status_code=201)
async def create_message(channel_id: str, request: Request):
    message = await forward("POST", f"{MESSAGES_URL}/api/v1/channels/{channel_id}/messages",
                            json=await json_body(request))
    return {**message, "author_name": await display_name(message["author_id"])}


# --- Ozy: traducciones y glosario ----------------------------------------

@app.post("/api/messages/{message_id}/translation", status_code=201)
async def create_translation(message_id: str, request: Request,
                             channel_id: str | None = None):
    body = await request.body()
    params = {"channel_id": channel_id} if channel_id else None
    return await forward("POST", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
                         params=params, content=body or b"{}",
                         headers={"Content-Type": "application/json"})


@app.get("/api/messages/{message_id}/translation")
async def get_translation(message_id: str, audience_level: str = "basico"):
    return await forward("GET", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
                         params={"audience_level": audience_level})


@app.get("/api/glossary")
async def list_glossary(ambito: str | None = None, estado: str | None = None):
    params = {k: v for k, v in {"ambito": ambito, "estado": estado}.items() if v}
    return await forward("GET", f"{OZY_URL}/api/v1/glossary", params=params)


@app.get("/api/glossary/{term}")
async def get_term(term: str):
    return await forward("GET", f"{OZY_URL}/api/v1/glossary/{term}")


@app.patch("/api/glossary/{entry_id}/validation")
async def validate_entry(entry_id: str, request: Request):
    return await forward("PATCH", f"{OZY_URL}/api/v1/glossary/{entry_id}/validation",
                         json=await json_body(request))


# --- Búsqueda (Elasticsearch, servicio "search") -------------------------

async def channel_names() -> dict[str, str]:
    try:
        channels = await forward("GET", f"{CHANNELS_URL}/api/v1/channels")
    except HTTPException:
        return {}
    return {c["id"]: c["name"] for c in channels}


async def search(path: str, request: Request):
    """Reenvía la búsqueda con sus filtros (los repetibles, como author_id, tal cual)
    y agrega nombres de autor y canal a cada resultado."""
    try:
        response = await client.get(f"{SEARCH_URL}{path}", headers=SEARCH_HEADERS,
                                    params=list(request.query_params.multi_items()))
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Búsqueda no disponible")
    if response.status_code == 202:  # índice aún construyéndose: se reintenta
        return JSONResponse(status_code=202, content=response.json(),
                            headers={"Retry-After": response.headers.get("Retry-After", "2")})
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)
    result = response.json()
    messages = result.get("messages", [])
    authors = {m["author_id"] for m in messages}
    names, channels = await asyncio.gather(
        asyncio.gather(*(display_name(a) for a in authors)), channel_names())
    names = dict(zip(authors, names))
    result["messages"] = [{**m, "author_name": names.get(m["author_id"]),
                           "channel_name": channels.get(m["channel_id"])}
                          for m in messages]
    return result


@app.get("/api/search/messages")
async def search_all(request: Request):
    return await search("/api/v1/search/messages", request)


@app.get("/api/channels/{channel_id}/messages/search")
async def search_channel(channel_id: str, request: Request):
    return await search(f"/api/v1/channels/{channel_id}/messages/search", request)


# --- Resúmenes (servicio "summaries") -------------------------------------

@app.post("/api/channels/{channel_id}/summaries", status_code=202)
async def request_summary(channel_id: str, request: Request):
    """Cuerpo opcional: {user_id?, timeInterval?: {start, end}}. Vacío = lo nuevo del canal."""
    body = await request.body()
    return await forward("POST", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                         json=(await json_body(request)) if body else None)


@app.get("/api/channels/{channel_id}/summaries")
async def list_summaries(channel_id: str, limit: int = 20, offset: int = 0):
    return await forward("GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                         params={"limit": limit, "offset": offset})


@app.get("/api/channels/{channel_id}/summaries/latest")
async def latest_summary(channel_id: str):
    return await forward("GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries/latest")


@app.get("/api/summaries/{summary_id}")
async def get_summary(summary_id: str):
    return await forward("GET", f"{SUMMARIES_URL}/api/v1/summaries/{summary_id}")
