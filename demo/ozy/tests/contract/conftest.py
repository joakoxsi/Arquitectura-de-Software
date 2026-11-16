"""Herramientas de las pruebas de contrato entre Ozy y el chat base.

Cada contrato es un JSON Schema versionado en `contracts/` y se verifica por los dos
lados, sin levantar el sistema ni acceder a la base de datos de otro servicio:

- **Consumidor (Ozy):** el código de Ozy acepta los ejemplos del contrato y los
  mensajes del proveedor real, y sigue funcionando si llegan campos extra.
- **Proveedor (users, channels, messages):** se carga el `app/main.py` real del
  servicio base en el mismo proceso, con una MongoDB en memoria propia de la
  prueba (nunca su base real) y sin broker. Lo que responde o publica debe
  cumplir el contrato.

Las llamadas HTTP que un proveedor hace a otro (messages valida autor y canal) se
resuelven en memoria con `InProcessHttp`, que las dirige a la TestClient del
servicio correspondiente.
"""
import importlib.util
import io
import json
import os
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

import jsonschema
import mongomock
import pytest
from fastapi.testclient import TestClient

CONTRACTS = Path(__file__).parent / "contracts"
DEMO = Path(__file__).resolve().parents[3]  # demo/: ahí viven los servicios base

format_checker = jsonschema.FormatChecker()


@format_checker.checks("date-time", raises=ValueError)
def _is_iso_datetime(value: object) -> bool:
    """date-time sin dependencias extra: ISO 8601 con zona horaria."""
    if not isinstance(value, str):
        return True
    return datetime.fromisoformat(value).tzinfo is not None


class Contract:
    def __init__(self, name: str):
        self.name = name
        self.schema = json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft202012Validator(self.schema,
                                                         format_checker=format_checker)

    @property
    def example(self):
        return self.schema["examples"][0]

    def errors(self, instance) -> list[str]:
        return [f"{'/'.join(map(str, error.absolute_path)) or '<raíz>'}: {error.message}"
                for error in self.validator.iter_errors(instance)]

    def assert_valid(self, instance) -> None:
        errors = self.errors(instance)
        assert not errors, f"No cumple el contrato {self.name}: {errors}"


@pytest.fixture
def contract():
    return Contract


def load_provider(service: str) -> ModuleType:
    """Carga el app/main.py real de un servicio base con su propia Mongo en memoria."""
    path = DEMO / service / "app" / "main.py"
    if not path.exists():
        pytest.skip(f"No está el código del proveedor {service} ({path})")
    spec = importlib.util.spec_from_file_location(f"chat_base_{service}_{uuid4().hex}", path)
    module = importlib.util.module_from_spec(spec)
    env = {"MONGODB_URL": "mongodb://contract-test"}
    with patch("pymongo.MongoClient", mongomock.MongoClient), patch.dict(os.environ, env):
        os.environ.pop("RABBITMQ_URL", None)  # sin broker: publica solo en su lista local
        spec.loader.exec_module(module)
    return module


class _Response:
    """Respuesta mínima compatible con lo que usan `urlopen` y `json.load`."""

    def __init__(self, status: int, content: bytes):
        self.status = status
        self._body = io.BytesIO(content)

    def read(self, *args):
        return self._body.read(*args)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class InProcessHttp:
    """Reemplazo de `urlopen` que dirige cada URL base a la TestClient de un servicio."""

    def __init__(self, routes: dict[str, TestClient]):
        self.routes = {base.rstrip("/"): client for base, client in routes.items()}
        self.calls: list[str] = []

    def urlopen(self, url, timeout=None):
        url = getattr(url, "full_url", url)
        self.calls.append(url)
        for base, client in self.routes.items():
            if url.startswith(base):
                response = client.get(url[len(base):])
                if response.status_code >= 400:
                    raise HTTPError(url, response.status_code, response.text, None,
                                    io.BytesIO(response.content))
                return _Response(response.status_code, response.content)
        raise AssertionError(f"URL sin proveedor en la prueba: {url}")


@pytest.fixture
def users_provider():
    module = load_provider("users")
    with TestClient(module.app) as client:
        yield module, client


@pytest.fixture
def channels_provider():
    module = load_provider("channels")
    with TestClient(module.app) as client:
        yield module, client


@pytest.fixture
def messages_provider(users_provider, channels_provider, monkeypatch):
    """messages real, que valida autor y canal contra users y channels reales."""
    module = load_provider("messages")
    http = InProcessHttp({module.USERS_URL: users_provider[1],
                          module.CHANNELS_URL: channels_provider[1]})
    monkeypatch.setattr(module, "urlopen", http.urlopen)
    with TestClient(module.app) as client:
        yield module, client


@pytest.fixture
def author_and_channel(users_provider, channels_provider):
    """Crea un autor y un canal en los proveedores reales (en memoria)."""
    user = users_provider[1].post("/api/v1/users", json={"display_name": "Ana"}).json()
    channel = channels_provider[1].post("/api/v1/channels", json={"name": "general"}).json()
    return user, channel


@pytest.fixture
def http_bridge():
    """Construye un `InProcessHttp` con las rutas {url_base: TestClient} indicadas."""
    return InProcessHttp


class StaticService:
    """Proveedor falso que responde rutas fijas: sirve para probar al consumidor
    con los ejemplos del contrato, sin el código del proveedor."""

    class _Reply:
        def __init__(self, status: int, body):
            self.status_code = status
            self.content = json.dumps(body).encode()
            self.text = self.content.decode()

    def __init__(self, routes: dict[str, object]):
        self.routes = routes

    def get(self, path: str):
        if path in self.routes:
            return self._Reply(200, self.routes[path])
        return self._Reply(404, {"detail": "Not found"})


@pytest.fixture
def static_service():
    return StaticService
