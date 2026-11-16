"""Arranque: espera a que MongoDB responda antes de crear índices y cargar el seed."""
import pytest
from pymongo.errors import ServerSelectionTimeoutError

from app import main


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
