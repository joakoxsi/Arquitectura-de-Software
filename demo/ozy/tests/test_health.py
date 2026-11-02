"""Probes de Kubernetes: liveness, readiness y arranque con MongoDB lento."""
from unittest.mock import MagicMock

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app import main


def test_liveness_ok_without_consumer(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_fails_when_consumer_thread_died(client, monkeypatch):
    dead = MagicMock()
    dead.is_alive.return_value = False
    monkeypatch.setattr(main, "consumer", dead)
    response = client.get("/health/live")
    assert response.status_code == 503
    assert response.json()["consumer"] == "dead"


def test_readiness_ok_when_mongo_answers(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["mongodb"] == "ok"
    assert response.json()["consumer"] == "disabled"


def test_readiness_fails_when_mongo_is_down(client, repos, monkeypatch):
    def down(*_args, **_kwargs):
        raise ServerSelectionTimeoutError("no servers")
    monkeypatch.setattr(repos.glossary.collection.database, "command", down)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["mongodb"] == "ServerSelectionTimeoutError"


def test_responses_say_which_instance_answered(client):
    response = client.get("/api/v1/glossary")
    assert response.headers["X-Ozy-Instance"] == main.INSTANCE


def test_startup_retries_until_mongo_is_up(repos, monkeypatch):
    calls = {"n": 0}
    original = repos.ensure_indexes

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ServerSelectionTimeoutError("starting")
        original()
    monkeypatch.setattr(repos, "ensure_indexes", flaky)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    main.prepare_database(timeout=60)
    assert calls["n"] == 3
    assert len(repos.glossary.find_all()) == 17


def test_startup_gives_up_after_timeout(repos, monkeypatch):
    def down():
        raise ServerSelectionTimeoutError("down")
    monkeypatch.setattr(repos, "ensure_indexes", down)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    with pytest.raises(ServerSelectionTimeoutError):
        main.prepare_database(timeout=0)
