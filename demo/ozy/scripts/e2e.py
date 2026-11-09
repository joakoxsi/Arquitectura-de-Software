"""Prueba de punta a punta de Ozy contra el sistema levantado.

Recorre el flujo completo con los servicios reales:
publicar mensaje -> Ozy lo consume -> traducir -> consultar -> validar candidato.

Uso local (con `docker compose up --build` corriendo, desde la carpeta demo/):
    python ozy/scripts/e2e.py

Uso en Kubernetes (Job `ozy-e2e`, ver ozy/k8s/README.md): las URLs llegan por
variables de entorno y, si existe RABBITMQ_URL, los eventos de Ozy se verifican
escuchando el exchange `chat` del broker compartido (con varias réplicas, la
lista en memoria de `/api/v1/events` es solo la del pod que responde).

Localmente solo usa la biblioteca estándar; en el clúster usa pika (viene en la
imagen de Ozy). Termina con código 0 si todo pasa.
"""
import base64
import json
import os
import random
import string
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

USERS = os.environ.get("USERS_URL", "http://localhost:8001")
CHANNELS = os.environ.get("CHANNELS_URL", "http://localhost:8002")
MESSAGES = os.environ.get("MESSAGES_URL", "http://localhost:8003")
OZY = os.environ.get("OZY_URL", "http://localhost:8004")
# API de administración de RabbitMQ (vacía = no se usa). En el clúster del curso
# normalmente no está expuesta; en ese caso se usa RABBITMQ_URL (AMQP).
RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672/api")
RABBITMQ_URL = os.environ.get("RABBITMQ_URL")
# "0": no esperar la cola de Ozy (en el clúster Ozy lee los mensajes por API).
OZY_QUEUE_CHECK = os.environ.get("OZY_QUEUE_CHECK", "1") != "0"
OZY_QUEUE = "ozy.chat.message.created"
OZY_EVENTS = ["chat.translation.created", "chat.glossary.candidate.registered",
              "chat.glossary.entry.validated"]
# Réplicas de Ozy que respondieron (cabecera X-Ozy-Instance).
instances: dict[str, int] = {}


class Failure(Exception):
    pass


last_response: dict = {}


def call(method: str, url: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    last_response.clear()
    # Solo la ruta: los logs pueden terminar en evidencia pública y las URLs
    # internas del clúster no deben quedar expuestas.
    last_response.update(request=f"{method} {urlsplit(url).path}")
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=5) as response:
            result = response.status, _json(response.read())
            instance = response.headers.get("X-Ozy-Instance")
    except HTTPError as error:
        result = error.code, _json(error.read())
        instance = error.headers.get("X-Ozy-Instance")
    if instance:
        instances[instance] = instances.get(instance, 0) + 1
    last_response.update(status=result[0], body=result[1])
    return result


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return raw.decode(errors="replace")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise Failure(message)
    print(f"  [OK] {message}")


def wait_until(description: str, probe, timeout: int) -> None:
    print(f"- Esperando: {description} (máx. {timeout}s)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if probe():
                print(f"  [OK] {description}")
                return
        except (URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(2)
    raise Failure(f"Tiempo agotado esperando: {description}")


def healthy(base: str) -> bool:
    return call("GET", f"{base}/health")[0] == 200


def rabbitmq_api_auth() -> str:
    auth = os.environ.get("RABBITMQ_API_AUTH")
    if not auth:
        password = os.environ.get("RABBITMQ_PASSWORD")
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if password is None and env_file.is_file():
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "RABBITMQ_PASSWORD":
                    password = value.strip()
        if not password:
            raise Failure("Configura RABBITMQ_PASSWORD en demo/.env o RABBITMQ_API_AUTH en el entorno.")
        auth = f"chat:{password}"
    return base64.b64encode(auth.encode()).decode("ascii")


def ozy_queue_exists() -> bool:
    if RABBITMQ_URL and not RABBITMQ_API:
        import pika
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        try:
            # passive=True: solo comprueba, no crea la cola.
            connection.channel().queue_declare(queue=OZY_QUEUE, passive=True)
            return True
        except pika.exceptions.ChannelClosedByBroker:
            return False
        finally:
            if connection.is_open:
                connection.close()
    status, _ = call("GET", f"{RABBITMQ_API}/queues/%2F/{OZY_QUEUE}",
                     headers={"Authorization": f"Basic {rabbitmq_api_auth()}"})
    return status == 200


class BrokerListener:
    """Cola temporal (exclusiva, se borra al cerrar) atada al exchange `chat`.

    Permite comprobar que los eventos de Ozy llegan de verdad al broker
    compartido, sin depender de qué réplica los publicó.
    """

    def __init__(self, url: str):
        import pika
        self.connection = pika.BlockingConnection(pika.URLParameters(url))
        self.channel = self.connection.channel()
        # Mismos parámetros que publisher.py. En un broker recién creado el exchange
        # aún no existe (Ozy lo declara al publicar su primer evento) y el bind fallaría.
        self.channel.exchange_declare(exchange="chat", exchange_type="topic")
        self.queue = self.channel.queue_declare(queue="", exclusive=True,
                                                auto_delete=True).method.queue
        for routing_key in OZY_EVENTS:
            self.channel.queue_bind(queue=self.queue, exchange="chat",
                                    routing_key=routing_key)

    def received(self) -> set[tuple[str, str]]:
        seen = set()
        while True:
            method, _, body = self.channel.basic_get(self.queue, auto_ack=True)
            if method is None:
                return seen
            event = json.loads(body)
            seen.add((event["type"], event["subject_id"]))

    def close(self) -> None:
        if self.connection.is_open:
            self.connection.close()


def main() -> None:
    # Sigla al azar para que el candidato sea nuevo en cada ejecución.
    acronym = "Q" + "".join(random.choices(string.ascii_uppercase, k=3))
    content = f"Hice el PR pero el pipeline falló; revisen el KPI del {acronym}"

    print("1. Servicios disponibles")
    for name, base in [("users", USERS), ("channels", CHANNELS),
                       ("messages", MESSAGES), ("ozy", OZY)]:
        wait_until(f"{name} responde /health", lambda base=base: healthy(base), 120)
    if OZY_QUEUE_CHECK and (RABBITMQ_API or RABBITMQ_URL):
        wait_until(f"la cola {OZY_QUEUE} existe en RabbitMQ", ozy_queue_exists, 90)
    listener = None
    if RABBITMQ_URL:
        import pika
        holder: list = []

        def broker_ready() -> bool:
            try:
                holder.append(BrokerListener(RABBITMQ_URL))
                return True
            except pika.exceptions.AMQPError:
                return False  # el broker puede estar terminando de arrancar
        wait_until("el broker acepta conexiones", broker_ready, 90)
        listener = holder[0]
    if listener:
        print(f"  [OK] escuchando {', '.join(OZY_EVENTS)} en el exchange chat")

    print("2. Publicar un mensaje técnico")
    status, user = call("POST", f"{USERS}/api/v1/users", {"display_name": "Ana E2E"})
    check(status == 201, "usuario creado")
    status, channel = call("POST", f"{CHANNELS}/api/v1/channels", {"name": "e2e"})
    check(status == 201, "canal creado")
    status, message = call("POST", f"{MESSAGES}/api/v1/channels/{channel['id']}/messages",
                           {"author_id": user["id"], "content": content})
    check(status == 201, f"mensaje creado: «{content}»")
    message_id = message["id"]

    if OZY_QUEUE_CHECK and (RABBITMQ_URL or RABBITMQ_API):
        print("3. Ozy consume chat.message.created del broker y traduce")
    else:
        print("3. Ozy lee el mensaje desde la API de messages y traduce")
    result = {}

    def translated() -> bool:
        # channel_id: si Ozy lee por API, sincroniza ese canal al momento.
        status, body = call("POST", f"{OZY}/api/v1/messages/{message_id}/translation"
                            f"?channel_id={channel['id']}", {"audience_level": "basico"})
        result.update(status=status, body=body)
        return status == 201
    # Sin broker, el sincronizador corre cada 10 s: se espera más que un ciclo.
    wait_until("Ozy recibió el mensaje en su read-model", translated, 60)
    translation = result["body"]
    terms = {term["term"]: term for term in translation["terms"]}
    check(list(terms) == ["PR", "Pipeline", "KPI", acronym],
          f"términos detectados en orden: {list(terms)}")
    check(terms["PR"]["ambiguous"] and len(terms["PR"]["meanings"]) == 3,
          "PR marcado como ambiguo con 3 ámbitos")
    check(not terms[acronym]["known"], f"{acronym} registrado como candidato")

    print("4. Consultar la traducción (botón «Explícamelo en simple»)")
    status, saved = call("GET", f"{OZY}/api/v1/messages/{message_id}/translation")
    check(status == 200 and saved["translation_id"] == translation["translation_id"],
          "GET devuelve la traducción guardada")
    check(saved["author"]["display_name"] == "Ana E2E",
          "incluye el display_name del autor consultado a users")

    print("5. Validar el candidato")
    status, term = call("GET", f"{OZY}/api/v1/glossary/{acronym}")
    check(status == 200 and term["entries"][0]["estado"] == "candidato",
          f"{acronym} aparece en el glosario como candidato")
    entry_id = term["entries"][0]["id"]
    status, entry = call("PATCH", f"{OZY}/api/v1/glossary/{entry_id}/validation",
                         {"estado": "validado", "validated_by": user["id"],
                          "ambito": "datos", "definition": "Sigla de prueba E2E."})
    check(status == 200 and entry["estado"] == "validado", "candidato validado")
    status, again = call("POST", f"{OZY}/api/v1/messages/{message_id}/translation")
    check(any(t["term"] == acronym and t["known"] for t in again["terms"]),
          f"la nueva traducción ya explica {acronym}")

    if listener:
        print("6. Eventos de Ozy recibidos en el exchange chat de su broker")
        published: set = set()

        def all_events_arrived() -> bool:
            published.update(listener.received())
            return {("chat.translation.created", translation["translation_id"]),
                    ("chat.glossary.candidate.registered", entry_id),
                    ("chat.glossary.entry.validated", entry_id)} <= published
        try:
            wait_until("los 3 eventos llegan al exchange chat", all_events_arrived, 20)
        except Failure:
            pass  # los check de abajo dicen cuál falta
        listener.close()
    else:
        print("6. Eventos publicados por Ozy")
        _, events = call("GET", f"{OZY}/api/v1/events")
        published = {(event["type"], event["subject_id"]) for event in events}
    check(("chat.translation.created", translation["translation_id"]) in published,
          "chat.translation.created")
    check(("chat.glossary.candidate.registered", entry_id) in published,
          "chat.glossary.candidate.registered")
    check(("chat.glossary.entry.validated", entry_id) in published,
          "chat.glossary.entry.validated")

    print("7. Errores")
    status, body = call("POST", f"{OZY}/api/v1/messages/no-existe/translation")
    check(status == 404 and body["detail"] == "Message not found",
          "404 para un mensaje desconocido")
    status, _ = call("POST", f"{OZY}/api/v1/messages/{message_id}/translation",
                     {"audience_level": "x"})
    check(status == 422, "422 para un nivel de audiencia inválido")

    print("8. Réplicas de Ozy que atendieron (cabecera X-Ozy-Instance)")
    for name, count in sorted(instances.items()):
        print(f"  - {name}: {count} respuestas")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except Failure as error:
        print(f"\n[FALLA] {error}")
        if "status" in last_response:
            print(f"Última respuesta: {last_response['request']} -> "
                  f"{last_response['status']} {last_response['body']}")
        if "read-model" in str(error):
            print("Revisa los logs de Ozy (`docker compose logs ozy` o "
                  "`kubectl logs -l app.kubernetes.io/name=ozy`): debe mostrar "
                  "'Consuming chat.message.created', y messages debe publicar en el "
                  "mismo broker y exchange `chat`.")
        sys.exit(1)
    print("\nTodo el flujo funciona de punta a punta.")
