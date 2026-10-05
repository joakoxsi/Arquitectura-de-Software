"""Ozy: traduce la jerga técnica de los mensajes del chat a lenguaje simple."""
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.config import RABBITMQ_URL
from app.consumer import MessageCreatedConsumer
from app.db import database
from app.domain import Ambito, AudienceLevel, Estado, GlossaryEntry
from app.publisher import (CANDIDATE_REGISTERED, ENTRY_REJECTED, ENTRY_VALIDATED,
                           TRANSLATION_CREATED, events, publish)
from app.repositories import Repositories
from app.seed import seed_glossary
from app.translator import translate
from app.users_client import get_display_name

logging.basicConfig(level=logging.INFO)
# El consumidor ya informa cada reintento; pika repite el mismo fallo con tracebacks.
logging.getLogger("pika").setLevel(logging.CRITICAL)
repos = Repositories(database)


@asynccontextmanager
async def lifespan(_: FastAPI):
    repos.ensure_indexes()
    seed_glossary(repos.glossary)
    consumer = None
    if RABBITMQ_URL:
        consumer = MessageCreatedConsumer(RABBITMQ_URL, repos.read_model)
        consumer.start()
    yield
    if consumer is not None:
        consumer.stop()
        consumer.join(timeout=5)


app = FastAPI(title="Chat Ozy", version="1.0.0", lifespan=lifespan)


class TranslationCreate(BaseModel):
    audience_level: AudienceLevel = AudienceLevel.BASICO


class ValidationUpdate(BaseModel):
    estado: Literal[Estado.VALIDADO, Estado.RECHAZADO]
    validated_by: str = Field(min_length=1)
    # Solo para completar un candidato, que aún no tiene definición ni ámbito.
    definition: str | None = Field(default=None, min_length=1, max_length=1_000)
    ambito: Ambito | None = None


def entry_view(entry: GlossaryEntry) -> dict:
    return entry.model_dump(mode="json", exclude={"term_normalized"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/messages/{message_id}/translation",
          status_code=status.HTTP_201_CREATED)
def create_translation(message_id: str, body: TranslationCreate | None = None):
    level = (body or TranslationCreate()).audience_level
    message = repos.read_model.get(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    translation, candidates = translate(message, level, repos.glossary)
    repos.translations.save(translation)
    for candidate in candidates:
        publish(CANDIDATE_REGISTERED, candidate.id,
                {"entry_id": candidate.id, "term": candidate.term,
                 "message_id": message.message_id, "channel_id": message.channel_id})
    publish(TRANSLATION_CREATED, translation.translation_id,
            {"translation_id": translation.translation_id,
             "message_id": translation.message_id,
             "channel_id": translation.channel_id,
             "audience_level": translation.audience_level.value,
             "terms": [term.term for term in translation.terms]})
    return translation.model_dump(mode="json")


@app.get("/api/v1/messages/{message_id}/translation")
def get_translation(message_id: str,
                    audience_level: AudienceLevel = AudienceLevel.BASICO):
    translation = repos.translations.get(message_id, audience_level.value)
    if translation is None:
        raise HTTPException(status_code=404, detail="Translation not found")
    message = repos.read_model.get(message_id)
    author_id = message.author_id if message else None
    return {**translation.model_dump(mode="json"),
            "author": {"id": author_id,
                       "display_name": get_display_name(author_id) if author_id else None}}


@app.get("/api/v1/glossary")
def list_glossary(ambito: Ambito | None = None, estado: Estado | None = None):
    return [entry_view(entry) for entry in repos.glossary.find_all(ambito, estado)]


@app.get("/api/v1/glossary/{term}")
def get_term(term: str):
    entries = repos.glossary.find_by_term(term)
    if not entries:
        raise HTTPException(status_code=404, detail="Term not found")
    usable = {entry.ambito for entry in entries
              if entry.definition and entry.estado != Estado.RECHAZADO}
    return {"term": entries[0].term, "ambiguous": len(usable) > 1,
            "entries": [entry_view(entry) for entry in entries]}


@app.patch("/api/v1/glossary/{entry_id}/validation")
def validate_entry(entry_id: str, body: ValidationUpdate):
    entry = repos.glossary.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Glossary entry not found")
    if body.estado == Estado.VALIDADO and not (
            (body.definition or entry.definition) and (body.ambito or entry.ambito)):
        raise HTTPException(status_code=422,
                            detail="A validated entry needs a definition and an ambito")
    try:
        updated = repos.glossary.set_estado(entry_id, body.estado, body.validated_by,
                                            body.definition, body.ambito)
    except DuplicateKeyError:
        raise HTTPException(status_code=409,
                            detail="Term already has an entry for that ambito")
    publish(ENTRY_VALIDATED if updated.estado == Estado.VALIDADO else ENTRY_REJECTED,
            updated.id,
            {"entry_id": updated.id, "term": updated.term,
             "ambito": updated.ambito.value if updated.ambito else None,
             "estado": updated.estado.value, "validated_by": updated.validated_by})
    return entry_view(updated)


@app.get("/api/v1/events")
def list_events():
    return events
