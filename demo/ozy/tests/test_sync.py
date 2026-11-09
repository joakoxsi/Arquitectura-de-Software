"""Sincronizador por API (sin broker), lease entre réplicas y eventos compartidos."""
import io
import json
from urllib.error import URLError

import mongomock
import pytest

from app import main, synchronizer
from app.repositories import Repositories
from app.synchronizer import MessageSynchronizer

CHANNELS = "http://channels"
MESSAGES = "http://messages"


class FakeChatBase:
    """Simula las rutas públicas de channels y messages."""

    def __init__(self):
        self.channels = {"c1": [], "c2": []}
        self.down: set[str] = set()
        self.calls: list[str] = []

    def add(self, channel_id, message_id, content="Hice el PR del ETL", author="a1"):
        self.channels[channel_id].append(
            {"id": message_id, "channel_id": channel_id, "author_id": author,
             "content": content, "created_at": "2026-11-02T00:00:00+00:00"})

    def urlopen(self, url, timeout=None):
        self.calls.append(url)
        if any(part in url for part in self.down):
            raise URLError("down")
        if url == f"{CHANNELS}/api/v1/channels":
            body = [{"id": cid, "name": cid} for cid in self.channels]
        else:
            cid = url.removeprefix(f"{MESSAGES}/api/v1/channels/").removesuffix("/messages")
            body = self.channels.get(cid, [])
        return io.BytesIO(json.dumps(body).encode())


@pytest.fixture
def base(monkeypatch):
    fake = FakeChatBase()
    monkeypatch.setattr(synchronizer, "urlopen", fake.urlopen)
    return fake


def make_sync(repos, instance="ozy-a"):
    return MessageSynchronizer(CHANNELS, MESSAGES, repos.read_model, repos.leases,
                               instance, interval=10)


def test_sync_copies_messages_through_the_acl(repos, base):
    base.add("c1", "m1")
    base.add("c2", "m2", content="Revisen el KPI")
    assert make_sync(repos).cycle() == 2
    assert repos.read_model.get("m2").content == "Revisen el KPI"
    assert repos.read_model.get("m1").channel_id == "c1"


def test_sync_is_idempotent_and_only_writes_new_messages(repos, base):
    base.add("c1", "m1")
    sync = make_sync(repos)
    assert sync.cycle() == 1
    assert sync.cycle() == 0
    base.add("c1", "m2")
    assert sync.cycle() == 1


def test_invalid_messages_are_skipped(repos, base):
    base.channels["c1"].append({"id": "bad", "channel_id": "c1"})  # sin content
    base.add("c1", "m1")
    assert make_sync(repos).cycle() == 1
    assert repos.read_model.get("bad") is None


def test_a_failing_channel_does_not_stop_the_others(repos, base):
    base.add("c1", "m1")
    base.add("c2", "m2")
    base.down.add("/channels/c1/")
    assert make_sync(repos).cycle() == 1
    assert repos.read_model.get("m2") is not None


def test_chat_base_down_does_not_crash_the_cycle(repos, base):
    base.down.add(CHANNELS)
    assert make_sync(repos).cycle() == 0


def test_only_one_replica_syncs_while_it_holds_the_lease(repos, base):
    base.add("c1", "m1")
    a, b = make_sync(repos, "ozy-a"), make_sync(repos, "ozy-b")
    assert a.cycle() == 1
    calls = len(base.calls)
    assert b.cycle() == 0
    assert len(base.calls) == calls  # la réplica b no llamó al chat base


def test_lease_can_be_taken_over_when_expired(repos):
    assert repos.leases.acquire("x", "ozy-a", ttl_seconds=-1)  # vence de inmediato
    assert repos.leases.acquire("x", "ozy-b", ttl_seconds=30)
    assert not repos.leases.acquire("x", "ozy-a", ttl_seconds=30)
    assert repos.leases.acquire("x", "ozy-b", ttl_seconds=30)  # renovación propia


def test_on_demand_sync_with_channel_id(client, repos, base, monkeypatch):
    base.add("c1", "m9")
    monkeypatch.setattr(main, "consumer", make_sync(repos))
    assert client.post("/api/v1/messages/m9/translation").status_code == 404
    response = client.post("/api/v1/messages/m9/translation?channel_id=c1")
    assert response.status_code == 201
    assert [t["term"] for t in response.json()["terms"]] == ["PR", "ETL"]


def test_on_demand_sync_failure_still_answers_404(client, repos, base, monkeypatch):
    base.down.add("/channels/c1/")
    monkeypatch.setattr(main, "consumer", make_sync(repos))
    response = client.post("/api/v1/messages/m9/translation?channel_id=c1")
    assert response.status_code == 404


def test_readiness_reports_ingestion_mode(client, repos, monkeypatch):
    monkeypatch.setattr(main, "consumer", make_sync(repos))
    body = client.get("/health/ready").json()
    assert body["ingestion"] == "api"
    assert body["consumer"] == "dead"  # el hilo no fue iniciado en el test


def test_events_are_shared_between_replicas(client, message):
    client.post("/api/v1/messages/m1/translation")
    other_replica = Repositories(main.repos.glossary.collection.database)
    types = [event["type"] for event in other_replica.events.list()]
    assert "chat.translation.created" in types


def test_with_own_broker_and_events_disabled_uses_the_api_synchronizer(repos, monkeypatch):
    """Clúster del curso: broker propio (solo para publicar) + lectura por API."""
    from fastapi.testclient import TestClient
    from app import main
    from app.synchronizer import MessageSynchronizer
    monkeypatch.setattr(main, "RABBITMQ_URL", "amqp://ozy-rabbitmq:5672/")
    monkeypatch.setattr(main, "CONSUME_MESSAGE_EVENTS", False)
    monkeypatch.setattr(main, "CHANNELS_URL", "http://channels:8000")
    monkeypatch.setattr(main, "MESSAGES_URL", "http://messages:8000")
    monkeypatch.setattr(MessageSynchronizer, "run", lambda self: None)
    with TestClient(main.app) as client:
        assert client.get("/health/ready").json()["ingestion"] == "api"


def test_compose_mode_consumes_from_the_broker(repos, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.consumer import MessageCreatedConsumer
    monkeypatch.setattr(main, "RABBITMQ_URL", "amqp://rabbitmq:5672/")
    monkeypatch.setattr(main, "CONSUME_MESSAGE_EVENTS", True)
    monkeypatch.setattr(MessageCreatedConsumer, "run", lambda self: None)
    with TestClient(main.app) as client:
        assert client.get("/health/ready").json()["ingestion"] == "broker"


def test_read_model_tiene_indice_por_canal_para_la_sincronizacion():
    """known_ids filtra por channel_id: sin este índice recorre toda la colección."""
    repos = Repositories(mongomock.MongoClient().chat_ozy)
    repos.ensure_indexes()
    repos.ensure_indexes()  # idempotente: varias réplicas lo ejecutan al arrancar

    indexes = repos.read_model.collection.index_information()
    keys = {tuple(info["key"]): info for info in indexes.values()}
    assert keys[(("message_id", 1),)].get("unique") is True  # se conserva
    assert (("channel_id", 1), ("message_id", 1)) in keys
