"""Prueba de punta a punta de Ozy contra el sistema levantado con docker compose.

Recorre el flujo completo con los servicios reales:
publicar mensaje -> Ozy lo consume -> traducir -> consultar -> validar candidato.

Uso (con `docker compose up --build` corriendo, desde la carpeta demo/):
    python ozy/scripts/e2e.py

Solo usa la biblioteca estándar de Python. Termina con código 0 si todo pasa.
"""
import base64
import json
import os
import random
import string
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERS = os.environ.get("USERS_URL", "http://localhost:8001")
CHANNELS = os.environ.get("CHANNELS_URL", "http://localhost:8002")
MESSAGES = os.environ.get("MESSAGES_URL", "http://localhost:8003")
OZY = os.environ.get("OZY_URL", "http://localhost:8004")
RABBITMQ_API = os.environ.get("RABBITMQ_API", "http://localhost:15672/api")
# Credenciales locales definidas en docker-compose.yaml.
RABBITMQ_AUTH = base64.b64encode(b"chat:chat").decode()
OZY_QUEUE = "ozy.chat.message.created"


class Failure(Exception):
    pass


last_response: dict = {}


def call(method: str, url: str, body: dict | None = None,
         headers: dict | None = None) -> tuple[int, object]:
    last_response.clear()
    last_response.update(request=f"{method} {url}")
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(request, timeout=5) as response:
            result = response.status, _json(response.read())
    except HTTPError as error:
        result = error.code, _json(error.read())
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


def ozy_queue_exists() -> bool:
    status, _ = call("GET", f"{RABBITMQ_API}/queues/%2F/{OZY_QUEUE}",
                     headers={"Authorization": f"Basic {RABBITMQ_AUTH}"})
    return status == 200


def main() -> None:
    # Sigla al azar para que el candidato sea nuevo en cada ejecución.
    acronym = "Q" + "".join(random.choices(string.ascii_uppercase, k=3))
    content = f"Hice el PR pero el pipeline falló; revisen el KPI del {acronym}"

    print("1. Servicios disponibles")
    for name, base in [("users", USERS), ("channels", CHANNELS),
                       ("messages", MESSAGES), ("ozy", OZY)]:
        wait_until(f"{name} responde /health", lambda base=base: healthy(base), 120)
    wait_until(f"la cola {OZY_QUEUE} existe en RabbitMQ", ozy_queue_exists, 90)

    print("2. Publicar un mensaje técnico")
    status, user = call("POST", f"{USERS}/api/v1/users", {"display_name": "Ana E2E"})
    check(status == 201, "usuario creado")
    status, channel = call("POST", f"{CHANNELS}/api/v1/channels", {"name": "e2e"})
    check(status == 201, "canal creado")
    status, message = call("POST", f"{MESSAGES}/api/v1/channels/{channel['id']}/messages",
                           {"author_id": user["id"], "content": content})
    check(status == 201, f"mensaje creado: «{content}»")
    message_id = message["id"]

    print("3. Ozy consume chat.message.created y traduce")
    result = {}

    def translated() -> bool:
        status, body = call("POST", f"{OZY}/api/v1/messages/{message_id}/translation",
                            {"audience_level": "basico"})
        result.update(status=status, body=body)
        return status == 201
    wait_until("Ozy recibió el mensaje en su read-model", translated, 30)
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
            print("Revisa `docker compose logs ozy messages`: Ozy debe mostrar "
                  "'Consuming chat.message.created' y messages debe tener RABBITMQ_URL.")
        sys.exit(1)
    print("\nTodo el flujo funciona de punta a punta.")
