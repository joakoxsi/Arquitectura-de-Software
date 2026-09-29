"""Fixtures comunes: Mongo en memoria (mongomock), sin broker y sin servicio users."""
import os
from unittest.mock import patch
from urllib.error import URLError

os.environ.setdefault("MONGODB_URL", "mongodb://test")
os.environ.pop("RABBITMQ_URL", None)  # sin broker: el consumidor no arranca

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


@pytest.fixture
def repos(monkeypatch):
    fresh = Repositories(mongomock.MongoClient().chat_ozy)
    monkeypatch.setattr(main, "repos", fresh)
    publisher.events.clear()
    return fresh


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
