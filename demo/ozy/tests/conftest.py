"""Fixtures comunes: BD de pruebas aislada, sin broker y sin servicio users.

Cada test recibe una base de datos nueva que se crea antes del test y se destruye
al terminar. Se inyecta en la API con `app.dependency_overrides[get_repos]`, así
que ninguna ruta toca la base real de Ozy.

Por defecto la base es MongoDB en memoria (mongomock). Con `OZY_TEST_MONGODB_URL`
(por ejemplo `mongodb://localhost:27017`) se usa una MongoDB real, en una base
temporal `chat_ozy_test_<uuid>` que se borra al final de cada test.
"""
import os
from unittest.mock import patch
from urllib.error import URLError
from uuid import uuid4

os.environ.setdefault("MONGODB_URL", "mongodb://test")
os.environ.pop("RABBITMQ_URL", None)  # sin broker: el consumidor no arranca
os.environ.pop("CHANNELS_URL", None)  # ni sincronizador por API
os.environ.pop("MESSAGES_URL", None)

import mongomock
import pytest
from fastapi.testclient import TestClient

with patch("pymongo.MongoClient", mongomock.MongoClient):
    from app import main, publisher
from app.domain import ReadMessage
from app.repositories import Repositories


@pytest.fixture(autouse=True)
def users_down(monkeypatch):
    """Ningún test llega a la red: users responde como caído salvo que se indique."""
    def fail(*_args, **_kwargs):
        raise URLError("users unavailable")
    monkeypatch.setattr("app.users_client.urlopen", fail)


TEST_MONGODB_URL = os.environ.get("OZY_TEST_MONGODB_URL")


@pytest.fixture
def test_database():
    """Crea una base de pruebas vacía y la destruye al terminar el test."""
    if TEST_MONGODB_URL:
        import pymongo
        mongo = pymongo.MongoClient(TEST_MONGODB_URL, serverSelectionTimeoutMS=2000)
    else:
        mongo = mongomock.MongoClient()
    database = mongo[f"chat_ozy_test_{uuid4().hex[:12]}"]
    yield database
    mongo.drop_database(database.name)
    mongo.close()


@pytest.fixture
def repos(test_database):
    """Repositorios sobre la base de pruebas, inyectados en la API por override."""
    fresh = Repositories(test_database)
    main.app.dependency_overrides[main.get_repos] = lambda: fresh
    publisher.events.clear()
    yield fresh
    main.app.dependency_overrides.pop(main.get_repos, None)


@pytest.fixture
def client(repos):
    with TestClient(main.app) as test_client:  # ejecuta el lifespan: índices + seed
        yield test_client


@pytest.fixture
def message(repos):
    msg = ReadMessage(message_id="m1", channel_id="c1", author_id="a1",
                      content="Hice el pr pero el Pipeline falló; revisen el KPI del ETL")
    repos.read_model.upsert(msg)
    return msg


def pytest_collection_modifyitems(items):
    """Marca cada test según su carpeta: unit, service, contract o integration."""
    for item in items:
        kind = item.path.parent.name
        if kind in {"unit", "service", "contract", "integration"}:
            item.add_marker(kind)
