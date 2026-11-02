"""Sincronizador de mensajes por API: alternativa al consumidor cuando no hay broker.

En el clúster del curso, `messages` no publica eventos (no tiene RABBITMQ_URL), así
que Ozy no puede enterarse de los mensajes nuevos por `chat.message.created`. En
ese caso Ozy los lee periódicamente por la API pública del chat base:

    GET {CHANNELS_URL}/api/v1/channels
    GET {MESSAGES_URL}/api/v1/channels/{channel_id}/messages

y los copia a su read-model pasando por la misma capa anticorrupción. Es el
patrón *polling consumer*: el resto de Ozy no cambia, porque sigue leyendo de su
read-model.

Con varias réplicas, solo una sincroniza a la vez (lease en la base propia de
Ozy), para no multiplicar la carga sobre el chat base compartido.
"""
import json
import logging
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from pymongo.errors import PyMongoError

from app import acl
from app.repositories import LeaseRepository, ReadModelRepository

logger = logging.getLogger("ozy.sync")

LEASE_NAME = "message-sync"
HTTP_TIMEOUT = 5


class SyncError(Exception):
    """El chat base no respondió como se esperaba; se reintenta en el próximo ciclo."""


def _get_json(url: str) -> object:
    try:
        with urlopen(url, timeout=HTTP_TIMEOUT) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        # Sin la URL en el mensaje: los logs pueden terminar en evidencia pública.
        raise SyncError(error.__class__.__name__) from error


class MessageSynchronizer(threading.Thread):
    def __init__(self, channels_url: str, messages_url: str,
                 read_model: ReadModelRepository, leases: LeaseRepository,
                 instance: str, interval: int = 10):
        super().__init__(name="ozy-sync", daemon=True)
        self.channels_url = channels_url.rstrip("/")
        self.messages_url = messages_url.rstrip("/")
        self.read_model = read_model
        self.leases = leases
        self.instance = instance
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info("Syncing messages from the chat base API every %ss", self.interval)
        while not self._stop_event.is_set():
            self.cycle()
            self._stop_event.wait(self.interval)

    def cycle(self) -> int:
        """Un ciclo: si esta réplica tiene el lease, sincroniza todo. Nunca lanza."""
        try:
            if not self.leases.acquire(LEASE_NAME, self.instance, self.interval * 3):
                return 0
            return self.sync_all()
        except (SyncError, PyMongoError) as error:
            logger.warning("Message sync failed (%s); retrying in %ss",
                           error.__class__.__name__ if isinstance(error, PyMongoError)
                           else error, self.interval)
            return 0

    def sync_all(self) -> int:
        channels = _get_json(f"{self.channels_url}/api/v1/channels")
        if not isinstance(channels, list):
            raise SyncError("unexpected channels response")
        added = 0
        for channel in channels:
            channel_id = channel.get("id") if isinstance(channel, dict) else None
            if not channel_id:
                continue
            try:
                added += self.sync_channel(str(channel_id))
            except SyncError as error:
                # Un canal con problemas no detiene la sincronización de los demás.
                logger.warning("Could not sync channel %s: %s", channel_id, error)
        if added:
            logger.info("Synced %s new message(s) from the chat base", added)
        return added

    def sync_channel(self, channel_id: str) -> int:
        """Copia al read-model los mensajes nuevos de un canal. Idempotente."""
        url = f"{self.messages_url}/api/v1/channels/{quote(channel_id, safe='')}/messages"
        messages = _get_json(url)
        if not isinstance(messages, list):
            raise SyncError("unexpected messages response")
        known = self.read_model.known_ids(channel_id)
        added = 0
        for raw in messages:
            try:
                message = acl.to_read_message(raw)
            except acl.InvalidEvent as error:
                logger.warning("Skipping invalid message: %s", error)
                continue
            if message.message_id not in known:
                self.read_model.upsert(message)
                added += 1
        return added
