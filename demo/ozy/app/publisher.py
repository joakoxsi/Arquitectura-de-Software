"""Publicación de eventos propios de Ozy (mismo patrón que `messages`)."""
import json
import logging
from datetime import datetime, timezone

import pika

from app.config import RABBITMQ_URL

logger = logging.getLogger("ozy.publisher")

EXCHANGE = "chat"
TRANSLATION_CREATED = "chat.translation.created"
CANDIDATE_REGISTERED = "chat.glossary.candidate.registered"
ENTRY_VALIDATED = "chat.glossary.entry.validated"
ENTRY_REJECTED = "chat.glossary.entry.rejected"
events: list[dict] = []


def publish(event_type: str, subject_id: str, data: dict) -> None:
    event = {"type": event_type, "subject_id": subject_id,
             "occurred_at": datetime.now(timezone.utc).isoformat(),
             "data": data}
    events.append(event)
    if RABBITMQ_URL:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            channel = connection.channel()
            channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic")
            channel.basic_publish(exchange=EXCHANGE, routing_key=event_type,
                                  body=json.dumps(event))
            connection.close()
        except (pika.exceptions.AMQPError, OSError) as error:
            # La lista local conserva el evento, igual que en `messages`.
            # En producción este fallo se tratará con outbox/reintentos.
            logger.warning("Could not publish %s: %s", event_type,
                           error.__class__.__name__)
