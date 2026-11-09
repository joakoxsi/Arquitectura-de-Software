"""API Gateway: único punto de entrada de la interfaz web.

La interfaz solo conoce este servicio. Expone:

- **GraphQL** en `/graphql` (queries y mutaciones; ver app/schema.py). Es la API
  que usa la interfaz. Abierto en el navegador, `/graphql` muestra GraphiQL.
- **REST** en `/api/...`, la versión anterior, que se mantiene por compatibilidad.

Ambas llaman al microservicio dueño del dato (users, channels, messages, ozy,
search, summaries) por sus APIs públicas (app/services.py) y, cuando ayuda a la
interfaz, combinan respuestas (ej. el nombre del autor de cada mensaje).
"""
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from strawberry.fastapi import GraphQLRouter

from app import services as svc
from app.schema import schema
from app.services import (CHANNELS_URL, OZY_URL, SUMMARIES_URL, USERS_URL,
                          ServiceError)

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

app = FastAPI(title="Chat API Gateway", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(GraphQLRouter(schema, graphql_ide="graphiql"), prefix="/graphql")


@app.on_event("shutdown")
async def close_client() -> None:
    await svc.client.aclose()


@app.exception_handler(ServiceError)
async def service_error(_: Request, error: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=error.status, content={"detail": error.detail})


async def json_body(request: Request) -> Any:
    """Cuerpo JSON de la petición; 400 si no es JSON válido en UTF-8."""
    try:
        return await request.json()
    except ValueError:  # incluye JSONDecodeError y UnicodeDecodeError
        raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON válido (UTF-8)")


# --- Salud ----------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/health")
async def services_health():
    return await svc.services_health()


# --- REST (compatibilidad) --------------------------------------------------

@app.post("/api/users", status_code=201)
async def create_user(request: Request):
    return svc.remember(await svc.call("POST", f"{USERS_URL}/api/v1/users",
                                       json=await json_body(request)))


@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    return svc.remember(await svc.call("GET", f"{USERS_URL}/api/v1/users/{user_id}"))


@app.get("/api/channels")
async def list_channels():
    return await svc.call("GET", f"{CHANNELS_URL}/api/v1/channels")


@app.post("/api/channels", status_code=201)
async def create_channel(request: Request):
    return await svc.call("POST", f"{CHANNELS_URL}/api/v1/channels",
                          json=await json_body(request))


@app.get("/api/channels/{channel_id}")
async def get_channel(channel_id: str):
    return await svc.call("GET", f"{CHANNELS_URL}/api/v1/channels/{channel_id}")


@app.get("/api/channels/{channel_id}/messages")
async def list_messages(channel_id: str):
    return await svc.list_messages(channel_id)


@app.post("/api/channels/{channel_id}/messages", status_code=201)
async def create_message(channel_id: str, request: Request):
    return await svc.create_message(channel_id, await json_body(request))


@app.post("/api/messages/{message_id}/translation", status_code=201)
async def create_translation(message_id: str, request: Request,
                             channel_id: str | None = None):
    body = await request.body()
    params = {"channel_id": channel_id} if channel_id else None
    return await svc.call("POST", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
                          params=params, content=body or b"{}",
                          headers={"Content-Type": "application/json"})


@app.get("/api/messages/{message_id}/translation")
async def get_translation(message_id: str, audience_level: str = "basico"):
    return await svc.call("GET", f"{OZY_URL}/api/v1/messages/{message_id}/translation",
                          params={"audience_level": audience_level})


@app.get("/api/glossary")
async def list_glossary(ambito: str | None = None, estado: str | None = None):
    params = {k: v for k, v in {"ambito": ambito, "estado": estado}.items() if v}
    return await svc.call("GET", f"{OZY_URL}/api/v1/glossary", params=params)


@app.get("/api/glossary/{term}")
async def get_term(term: str):
    return await svc.call("GET", f"{OZY_URL}/api/v1/glossary/{term}")


@app.patch("/api/glossary/{entry_id}/validation")
async def validate_entry(entry_id: str, request: Request):
    return await svc.call("PATCH", f"{OZY_URL}/api/v1/glossary/{entry_id}/validation",
                          json=await json_body(request))


async def search(channel_id: str | None, request: Request):
    status, result = await svc.search(svc.search_path(channel_id),
                                      list(request.query_params.multi_items()))
    if status == 202:
        return JSONResponse(status_code=202, content=result,
                            headers={"Retry-After": str(result["retry_after"])})
    return result


@app.get("/api/search/messages")
async def search_all(request: Request):
    return await search(None, request)


@app.get("/api/channels/{channel_id}/messages/search")
async def search_channel(channel_id: str, request: Request):
    return await search(channel_id, request)


@app.post("/api/channels/{channel_id}/summaries", status_code=202)
async def request_summary(channel_id: str, request: Request):
    """Cuerpo opcional: {user_id?, timeInterval?: {start, end}}. Vacío = lo nuevo del canal."""
    body = await request.body()
    return await svc.call("POST", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                          json=(await json_body(request)) if body else None)


@app.get("/api/channels/{channel_id}/summaries")
async def list_summaries(channel_id: str, limit: int = 20, offset: int = 0):
    return await svc.call("GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries",
                          params={"limit": limit, "offset": offset})


@app.get("/api/channels/{channel_id}/summaries/latest")
async def latest_summary(channel_id: str):
    return await svc.call(
        "GET", f"{SUMMARIES_URL}/api/v1/channels/{channel_id}/summaries/latest")


@app.get("/api/summaries/{summary_id}")
async def get_summary(summary_id: str):
    return await svc.call("GET", f"{SUMMARIES_URL}/api/v1/summaries/{summary_id}")
