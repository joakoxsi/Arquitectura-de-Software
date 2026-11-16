"""Prueba de integración: Ozy junto a users, channels y messages reales en Docker Compose.

Demuestra el flujo de la capacidad con los servicios de verdad, cada uno con su
propia MongoDB y comunicados por RabbitMQ:

    users + channels  →  messages publica chat.message.created  →  RabbitMQ
    →  Ozy lo guarda en su read-model  →  traducción  →  nombre del autor desde users
    →  Ozy publica chat.translation.created / chat.glossary.*  →  RabbitMQ

Requiere el entorno de `demo/docker-compose.test.yaml`. Lo más simple es
`ozy/scripts/integracion.sh`, que lo levanta, corre esta prueba y lo destruye.
No corre con `pytest` a secas (ver `pytest.ini`): hay que pedirla con
`-m integration`.
"""
import base64
import json
import os
import random
import string
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pika
import pytest

pytestmark = pytest.mark.integration

USERS = os.environ.get("IT_USERS_URL", "http://localhost:18001")
CHANNELS = os.environ.get("IT_CHANNELS_URL", "http://localhost:18002")
MESSAGES = os.environ.get("IT_MESSAGES_URL", "http://localhost:18003")
OZY = os.environ.get("IT_OZY_URL", "http://localhost:18004")
RABBITMQ_PASSWORD = os.environ.get("OZY_TEST_RABBITMQ_PASSWORD", "integracion-local")
RABBITMQ_URL = os.environ.get(
    "IT_RABBITMQ_URL", f"amqp://chat:{RABBITMQ_PASSWORD}@localhost:18672/")
RABBITMQ_API = os.environ.get("IT_RABBITMQ_API", "http://localhost:18673/api")
OZY_QUEUE = "ozy.chat.message.created"
TIMEOUT = int(os.environ.get("IT_TIMEOUT", "30"))


def call(method: str, url: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"null")
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def wait_until(description: str, probe, timeout: int = TIMEOUT):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result:
                return result
        except (URLError, OSError, ValueError) as error:
            last_error = error
        time.sleep(0.5)
    pytest.fail(f"Tiempo agotado esperando: {description} (último error: {last_error})")


def sigla_al_azar() -> str:
    """Sigla nueva en cada corrida: Ozy la registra como candidato sin choques."""
    return "Q" + "".join(random.choices(string.ascii_uppercase, k=4))


class BrokerListener:
    """Cola exclusiva en el exchange `chat` para ver los eventos que publica Ozy."""

    ROUTING_KEYS = ["chat.translation.created", "chat.glossary.#"]

    def __init__(self, url: str):
        self.connection = pika.BlockingConnection(pika.URLParameters(url))
        self.channel = self.connection.channel()
        self.channel.exchange_declare(exchange="chat", exchange_type="topic")
        self.queue = self.channel.queue_declare(queue="", exclusive=True).method.queue
        for key in self.ROUTING_KEYS:
            self.channel.queue_bind(queue=self.queue, exchange="chat", routing_key=key)
        self.received: list[dict] = []

    def drain(self) -> list[dict]:
        while True:
            method, _props, body = self.channel.basic_get(self.queue, auto_ack=True)
            if method is None:
                return self.received
            self.received.append(json.loads(body))

    def wait_for(self, event_type: str, subject_id: str) -> dict:
        def found():
            return next((event for event in self.drain()
                         if event["type"] == event_type
                         and event["subject_id"] == subject_id), None)
        return wait_until(f"evento {event_type} de {subject_id} en RabbitMQ", found)

    def close(self) -> None:
        self.connection.close()


# --- Fixtures del flujo (una vez por módulo) --------------------------------------

@pytest.fixture(scope="module")
def sistema():
    """Espera a que el sistema esté listo y a que Ozy tenga su cola en RabbitMQ."""
    for name, base in {"users": USERS, "channels": CHANNELS,
                       "messages": MESSAGES, "ozy": OZY}.items():
        wait_until(f"{name} en {base}",
                   lambda base=base: call("GET", f"{base}/health")[0] == 200)
    auth = base64.b64encode(f"chat:{RABBITMQ_PASSWORD}".encode()).decode()

    def ozy_queue_exists() -> bool:
        status, _ = call("GET", f"{RABBITMQ_API}/queues/%2F/{OZY_QUEUE}",
                         headers={"Authorization": f"Basic {auth}"})
        return status == 200
    # Los mensajes publicados antes de que exista la cola se pierden (ADR-001).
    wait_until(f"cola {OZY_QUEUE} de Ozy", ozy_queue_exists)


@pytest.fixture(scope="module")
def broker(sistema):
    listener = BrokerListener(RABBITMQ_URL)
    yield listener
    listener.close()


@pytest.fixture(scope="module")
def flujo(broker):
    """Crea autor, canal y un mensaje técnico en el chat base y espera a que Ozy lo traduzca."""
    nombre = f"Ana {random.randint(1000, 9999)}"
    sigla = sigla_al_azar()
    status, user = call("POST", f"{USERS}/api/v1/users", {"display_name": nombre})
    assert status == 201, user
    status, channel = call("POST", f"{CHANNELS}/api/v1/channels", {"name": "integracion"})
    assert status == 201, channel
    contenido = f"Hice el PR pero el pipeline falló; revisen el KPI del {sigla}"
    status, message = call("POST", f"{MESSAGES}/api/v1/channels/{channel['id']}/messages",
                           {"author_id": user["id"], "content": contenido})
    assert status == 201, message

    def translated():
        status, body = call("POST", f"{OZY}/api/v1/messages/{message['id']}/translation",
                            {"audience_level": "basico"})
        return body if status == 201 else None
    translation = wait_until("que Ozy reciba chat.message.created y traduzca", translated)
    return {"user": user, "channel": channel, "message": message, "sigla": sigla,
            "translation": translation}


# --- Pruebas ----------------------------------------------------------------------

def test_ozy_consume_eventos_del_broker(sistema):
    status, body = call("GET", f"{OZY}/health/ready")
    assert status == 200
    assert (body["mongodb"], body["consumer"], body["ingestion"]) == \
        ("ok", "running", "broker")


def test_el_mensaje_de_messages_llega_a_ozy_y_se_traduce(flujo):
    translation = flujo["translation"]
    assert translation["message_id"] == flujo["message"]["id"]
    assert translation["channel_id"] == flujo["channel"]["id"]
    terms = {term["term"]: term for term in translation["terms"]}
    assert list(terms) == ["PR", "Pipeline", "KPI", flujo["sigla"]]
    assert terms["PR"]["ambiguous"]
    assert not terms[flujo["sigla"]]["known"]
    assert "significa cosas distintas" in translation["explanation"]


def test_la_traduccion_trae_el_nombre_del_autor_desde_users(flujo):
    status, body = call("GET", f"{OZY}/api/v1/messages/{flujo['message']['id']}/translation")
    assert status == 200
    assert body["translation_id"] == flujo["translation"]["translation_id"]
    assert body["author"] == {"id": flujo["user"]["id"],
                              "display_name": flujo["user"]["display_name"]}


def test_ozy_publica_sus_eventos_en_rabbitmq(flujo, broker):
    translation = flujo["translation"]
    event = broker.wait_for("chat.translation.created", translation["translation_id"])
    assert event["data"]["message_id"] == flujo["message"]["id"]
    assert event["data"]["terms"] == ["PR", "Pipeline", "KPI", flujo["sigla"]]
    status, entries = call("GET", f"{OZY}/api/v1/glossary/{flujo['sigla']}")
    assert status == 200
    entry_id = entries["entries"][0]["id"]
    candidate = broker.wait_for("chat.glossary.candidate.registered", entry_id)
    assert candidate["data"]["channel_id"] == flujo["channel"]["id"]


def test_validar_el_candidato_lo_vuelve_conocido(flujo, broker):
    sigla = flujo["sigla"]
    _, entries = call("GET", f"{OZY}/api/v1/glossary/{sigla}")
    entry_id = entries["entries"][0]["id"]
    status, body = call("PATCH", f"{OZY}/api/v1/glossary/{entry_id}/validation", {
        "estado": "validado", "validated_by": flujo["user"]["id"], "ambito": "datos",
        "definition": "Sigla validada en la prueba de integración."})
    assert status == 200, body
    assert body["validated_by"] == flujo["user"]["id"]
    broker.wait_for("chat.glossary.entry.validated", entry_id)
    status, again = call("POST",
                         f"{OZY}/api/v1/messages/{flujo['message']['id']}/translation",
                         {"audience_level": "experto"})
    assert status == 201
    validada = again["terms"][-1]
    assert (validada["term"], validada["known"]) == (sigla, True)
    assert validada["meanings"][0]["ambito"] == "datos"


def test_un_mensaje_rechazado_por_messages_no_llega_a_ozy(flujo):
    status, _ = call("POST",
                     f"{MESSAGES}/api/v1/channels/{flujo['channel']['id']}/messages",
                     {"author_id": "autor-inexistente", "content": "El deploy falló"})
    assert status == 422
    status, body = call("POST", f"{OZY}/api/v1/messages/{quote('no-publicado')}/translation")
    assert status == 404
    assert body["detail"] == "Message not found"


def test_messages_rechaza_un_canal_inexistente(flujo):
    status, body = call("POST", f"{MESSAGES}/api/v1/channels/no-existe/messages",
                        {"author_id": flujo["user"]["id"], "content": "Hola"})
    assert status == 404
    assert body["detail"] == "Channel not found"
