import io
import json
from unittest.mock import MagicMock

import pika

from app import publisher, users_client


def test_publishes_to_chat_exchange_with_event_type_as_routing_key(monkeypatch):
    publisher.events.clear()
    connection = MagicMock()
    monkeypatch.setattr(publisher, "RABBITMQ_URL", "amqp://x")
    monkeypatch.setattr(publisher.pika, "BlockingConnection", MagicMock(return_value=connection))
    publisher.publish("chat.translation.created", "t1", {"translation_id": "t1"})
    call = connection.channel.return_value.basic_publish.call_args.kwargs
    assert call["exchange"] == "chat"
    assert call["routing_key"] == "chat.translation.created"
    assert json.loads(call["body"])["data"] == {"translation_id": "t1"}


def test_broker_failure_keeps_event_locally(monkeypatch):
    publisher.events.clear()
    monkeypatch.setattr(publisher, "RABBITMQ_URL", "amqp://x")
    monkeypatch.setattr(publisher.pika, "BlockingConnection",
                        MagicMock(side_effect=pika.exceptions.AMQPConnectionError()))
    publisher.publish("chat.translation.created", "t1", {})
    assert [event["subject_id"] for event in publisher.events] == ["t1"]


def test_display_name_from_users(monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = io.BytesIO(b'{"id": "a1", "display_name": "Ana"}')
    opener = MagicMock(return_value=response)
    monkeypatch.setattr(users_client, "urlopen", opener)
    assert users_client.get_display_name("a1") == "Ana"
    assert opener.call_args.args[0].endswith("/api/v1/users/a1")


def test_display_name_is_none_when_users_fails():
    assert users_client.get_display_name("a1") is None  # conftest simula users caído
