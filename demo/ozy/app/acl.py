"""Capa anticorrupción: traduce eventos externos al modelo propio de Ozy.

Es el único módulo que conoce la forma de los eventos de `messages`. Ningún dato
del evento externo sale de aquí salvo como `ReadMessage`.

Formatos aceptados para `chat.message.created`:
- Sobre publicado por `messages`:
  {"type", "subject_id", "occurred_at", "data": {"id", "channel_id",
   "author_id", "content", "created_at"}}
- Payload plano del contrato: {"message_id", "channel_id", "author_id", "content"}
"""
import json

from app.domain import ReadMessage

MESSAGE_CREATED = "chat.message.created"


class InvalidEvent(ValueError):
    """El evento no se puede mapear al modelo de Ozy; no tiene sentido reintentarlo."""


def _opaque_id(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    raise InvalidEvent(f"Missing field: {keys[0]}")


def to_read_message(body: bytes | str | dict) -> ReadMessage:
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidEvent("Event body is not valid JSON") from error
    if not isinstance(body, dict):
        raise InvalidEvent("Event body must be a JSON object")

    event_type = body.get("type")
    if event_type is not None and event_type != MESSAGE_CREATED:
        raise InvalidEvent(f"Unexpected event type: {event_type}")

    payload = body.get("data") if isinstance(body.get("data"), dict) else body
    content = payload.get("content")
    if not isinstance(content, str):
        raise InvalidEvent("Missing field: content")

    return ReadMessage(
        message_id=_opaque_id(payload, "message_id", "id"),
        channel_id=_opaque_id(payload, "channel_id"),
        author_id=_opaque_id(payload, "author_id"),
        content=content,
    )
