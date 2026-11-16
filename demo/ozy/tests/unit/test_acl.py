import json

import pytest

from app import acl

ENVELOPE = {
    "type": "chat.message.created", "subject_id": "m1", "occurred_at": "2026-09-29T00:00:00",
    "data": {"id": "m1", "channel_id": "c1", "author_id": "a1",
             "content": "El PR está listo", "created_at": "2026-09-29T00:00:00"},
}


def test_maps_envelope_published_by_messages():
    message = acl.to_read_message(json.dumps(ENVELOPE).encode())
    assert (message.message_id, message.channel_id, message.author_id, message.content) == \
        ("m1", "c1", "a1", "El PR está listo")


def test_maps_flat_contract_payload():
    message = acl.to_read_message(
        {"message_id": "m2", "channel_id": "c1", "author_id": "a1", "content": "hola"})
    assert message.message_id == "m2"


def test_does_not_leak_external_fields():
    fields = set(acl.to_read_message(ENVELOPE).model_dump())
    assert fields == {"message_id", "channel_id", "author_id", "content", "received_at"}


def test_ids_are_kept_as_opaque_strings():
    message = acl.to_read_message(
        {"message_id": 42, "channel_id": 7, "author_id": 1, "content": "x"})
    assert (message.message_id, message.channel_id, message.author_id) == ("42", "7", "1")


@pytest.mark.parametrize("body", [
    b"not json",
    b"[1, 2]",
    {"type": "chat.user.created", "data": {"id": "u1"}},
    {"data": {"id": "m1", "channel_id": "c1", "author_id": "a1"}},
    {"data": {"channel_id": "c1", "author_id": "a1", "content": "x"}},
    {"message_id": "  ", "channel_id": "c1", "author_id": "a1", "content": "x"},
])
def test_rejects_invalid_events(body):
    with pytest.raises(acl.InvalidEvent):
        acl.to_read_message(body)
