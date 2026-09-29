"""Consumidor de `chat.message.created` que alimenta el read-model de Ozy."""
import logging
import threading

import pika
from pymongo.errors import PyMongoError

from app import acl
from app.repositories import ReadModelRepository

logger = logging.getLogger("ozy.consumer")

EXCHANGE = "chat"
QUEUE = "ozy.chat.message.created"
MAX_RETRY_DELAY = 30


def handle_message_created(body: bytes, read_model: ReadModelRepository) -> None:
    """ACL + upsert idempotente: reprocesar el mismo evento no duplica nada."""
    read_model.upsert(acl.to_read_message(body))


class MessageCreatedConsumer(threading.Thread):
    """Hilo que consume del broker y se reconecta con backoff si se cae."""

    def __init__(self, url: str, read_model: ReadModelRepository):
        super().__init__(name="ozy-consumer", daemon=True)
        self.url = url
        self.read_model = read_model
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        delay = 1
        while not self._stop_event.is_set():
            try:
                self._consume()
                delay = 1
            except (pika.exceptions.AMQPError, OSError) as error:
                logger.warning("RabbitMQ unavailable (%s); retrying in %ss",
                               error.__class__.__name__, delay)
                self._stop_event.wait(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)

    def _consume(self) -> None:
        connection = pika.BlockingConnection(pika.URLParameters(self.url))
        try:
            channel = connection.channel()
            # Mismos parámetros que usa `messages`; si difieren, el broker rechaza
            # la declaración (PRECONDITION_FAILED).
            channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic")
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.queue_bind(queue=QUEUE, exchange=EXCHANGE,
                               routing_key=acl.MESSAGE_CREATED)
            channel.basic_qos(prefetch_count=10)
            logger.info("Consuming %s from queue %s", acl.MESSAGE_CREATED, QUEUE)
            for method, _, body in channel.consume(QUEUE, inactivity_timeout=1):
                if self._stop_event.is_set():
                    break
                if method is None:
                    continue
                self._process(channel, method.delivery_tag, body)
            channel.cancel()
        finally:
            if connection.is_open:
                connection.close()

    def _process(self, channel, delivery_tag: int, body: bytes) -> None:
        try:
            handle_message_created(body, self.read_model)
        except acl.InvalidEvent as error:
            logger.warning("Discarding invalid event: %s", error)
            channel.basic_nack(delivery_tag, requeue=False)
        except PyMongoError:
            logger.exception("Could not store message; requeueing")
            channel.basic_nack(delivery_tag, requeue=True)
            self._stop_event.wait(1)
        else:
            channel.basic_ack(delivery_tag)
