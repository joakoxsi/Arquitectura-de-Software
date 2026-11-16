"""Contrato del evento que publica Ozy: chat.translation.created (Ozy es el proveedor)."""
import json
from unittest.mock import MagicMock

from app import publisher

NAME = "chat.translation.created"


def test_el_ejemplo_documentado_cumple_el_contrato(contract):
    contract(NAME).assert_valid(contract(NAME).example)


def test_ozy_publica_al_broker_un_evento_que_cumple_el_contrato(
        contract, client, message, monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(publisher, "RABBITMQ_URL", "amqp://contrato")
    monkeypatch.setattr(publisher.pika, "BlockingConnection",
                        MagicMock(return_value=connection))
    client.post("/api/v1/messages/m1/translation", json={"audience_level": "intermedio"})
    published = [call.kwargs for call in
                 connection.channel.return_value.basic_publish.call_args_list
                 if call.kwargs["routing_key"] == NAME]
    assert len(published) == 1
    assert published[0]["exchange"] == "chat"
    event = json.loads(published[0]["body"])
    contract(NAME).assert_valid(event)
    assert event["subject_id"] == event["data"]["translation_id"]


def test_un_evento_sin_terms_rompe_el_contrato(contract):
    event = json.loads(json.dumps(contract(NAME).example))
    del event["data"]["terms"]
    assert contract(NAME).errors(event)
