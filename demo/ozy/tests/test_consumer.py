import json
from unittest.mock import MagicMock

import pika
from pymongo.errors import PyMongoError

from app import consumer
from app.consumer import MessageCreatedConsumer, handle_message_created

EVENT = json.dumps({
    "type": "chat.message.created", "subject_id": "m1", "occurred_at": "t",
    "data": {"id": "m1", "channel_id": "c1", "author_id": "a1", "content": "El PR"},
}).encode()


def test_handler_is_idempotent(repos):
    handle_message_created(EVENT, repos.read_model)
    first = repos.read_model.get("m1")
    handle_message_created(EVENT, repos.read_model)
    assert repos.read_model.collection.count_documents({}) == 1
    assert repos.read_model.get("m1").received_at == first.received_at


def test_valid_event_is_stored_and_acked(repos):
    channel = MagicMock()
    MessageCreatedConsumer("amqp://x", repos.read_model)._process(channel, 7, EVENT)
    channel.basic_ack.assert_called_once_with(7)
    assert repos.read_model.get("m1").content == "El PR"


def test_invalid_event_is_discarded_without_requeue(repos):
    channel = MagicMock()
    MessageCreatedConsumer("amqp://x", repos.read_model)._process(channel, 7, b"not json")
    channel.basic_nack.assert_called_once_with(7, requeue=False)
    channel.basic_ack.assert_not_called()


def test_storage_failure_requeues_the_event(repos, monkeypatch):
    channel = MagicMock()
    worker = MessageCreatedConsumer("amqp://x", repos.read_model)
    monkeypatch.setattr(repos.read_model, "upsert", MagicMock(side_effect=PyMongoError()))
    monkeypatch.setattr(worker._stop_event, "wait", lambda _seconds: None)
    worker._process(channel, 7, EVENT)
    channel.basic_nack.assert_called_once_with(7, requeue=True)


def test_reconnects_with_exponential_backoff(repos, monkeypatch):
    connect = MagicMock(side_effect=pika.exceptions.AMQPConnectionError())
    monkeypatch.setattr(consumer.pika, "BlockingConnection", connect)
    worker = MessageCreatedConsumer("amqp://x", repos.read_model)
    delays = []

    def wait(seconds):
        delays.append(seconds)
        if len(delays) == 7:
            worker.stop()
    monkeypatch.setattr(worker._stop_event, "wait", wait)

    worker.run()
    assert delays == [1, 2, 4, 8, 16, 30, 30]
    assert connect.call_count == 7


def test_declares_exchange_like_messages_and_a_durable_queue(repos, monkeypatch):
    channel = MagicMock()
    channel.consume.return_value = iter([])
    connection = MagicMock()
    connection.channel.return_value = channel
    monkeypatch.setattr(consumer.pika, "BlockingConnection", MagicMock(return_value=connection))
    MessageCreatedConsumer("amqp://x", repos.read_model)._consume()
    channel.exchange_declare.assert_called_once_with(exchange="chat", exchange_type="topic")
    channel.queue_declare.assert_called_once_with(queue=consumer.QUEUE, durable=True)
    channel.queue_bind.assert_called_once_with(
        queue=consumer.QUEUE, exchange="chat", routing_key="chat.message.created")
