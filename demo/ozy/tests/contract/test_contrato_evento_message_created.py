"""Contrato del evento chat.message.created: lo publica `messages` y lo consume Ozy."""
import json

import pytest

from app import acl
from app.consumer import handle_message_created

NAME = "chat.message.created"


# --- Lado consumidor: Ozy entiende lo que dice el contrato ------------------------

def test_ozy_mapea_el_ejemplo_del_contrato(contract):
    event = contract(NAME).example
    contract(NAME).assert_valid(event)  # el ejemplo no puede desviarse del schema
    message = acl.to_read_message(json.dumps(event).encode())
    assert (message.message_id, message.channel_id, message.author_id, message.content) \
        == (event["data"]["id"], event["data"]["channel_id"],
            event["data"]["author_id"], event["data"]["content"])


def test_ozy_tolera_campos_nuevos_del_proveedor(contract):
    """Agregar campos es un cambio compatible: Ozy debe ignorarlos."""
    event = json.loads(json.dumps(contract(NAME).example))
    event["version"] = 2
    event["data"]["edited"] = False
    event["data"]["attachments"] = []
    contract(NAME).assert_valid(event)
    assert acl.to_read_message(event).content == event["data"]["content"]


@pytest.mark.parametrize("breaking_change", [
    lambda e: e["data"].pop("content"),
    lambda e: e["data"].pop("channel_id"),
    lambda e: e["data"].pop("id"),
    lambda e: e.update(type="chat.message.deleted"),
])
def test_un_evento_que_rompe_el_contrato_tambien_lo_rechaza_ozy(contract, breaking_change):
    """Contrato y capa anticorrupción están de acuerdo en qué es inválido."""
    event = json.loads(json.dumps(contract(NAME).example))
    breaking_change(event)
    assert contract(NAME).errors(event)
    with pytest.raises(acl.InvalidEvent):
        acl.to_read_message(event)


# --- Lado proveedor: lo que publica el `messages` real cumple el contrato ---------

def publish_message(messages_provider, author, channel, content="Hice el PR del ETL"):
    module, client = messages_provider
    response = client.post(f"/api/v1/channels/{channel['id']}/messages",
                           json={"author_id": author["id"], "content": content})
    assert response.status_code == 201, response.text
    return response.json(), module.events[-1]


def test_messages_publica_un_evento_que_cumple_el_contrato(
        contract, messages_provider, author_and_channel):
    message, event = publish_message(messages_provider, *author_and_channel)
    contract(NAME).assert_valid(event)
    assert event["subject_id"] == message["id"] == event["data"]["id"]


def test_el_evento_real_de_messages_llega_al_read_model_de_ozy(
        messages_provider, author_and_channel, repos):
    author, channel = author_and_channel
    message, event = publish_message(messages_provider, author, channel)
    # Así viaja por RabbitMQ: JSON serializado (ADR-002).
    handle_message_created(json.dumps(event).encode(), repos.read_model)
    stored = repos.read_model.get(message["id"])
    assert (stored.channel_id, stored.author_id, stored.content) == \
        (channel["id"], author["id"], "Hice el PR del ETL")


def test_messages_no_publica_si_rechaza_la_peticion(messages_provider, author_and_channel):
    """Un mensaje con autor inexistente no genera evento: Ozy no recibe basura."""
    module, client = messages_provider
    _, channel = author_and_channel
    response = client.post(f"/api/v1/channels/{channel['id']}/messages",
                           json={"author_id": "no-existe", "content": "hola"})
    assert response.status_code == 422
    assert module.events == []
