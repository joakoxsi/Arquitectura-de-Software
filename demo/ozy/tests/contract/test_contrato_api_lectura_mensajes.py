"""Contrato de lectura por API que usa el sincronizador de Ozy (clúster sin broker):

    GET {channels}/api/v1/channels
    GET {messages}/api/v1/channels/{channel_id}/messages
"""
from app.repositories import Repositories
from app.synchronizer import MessageSynchronizer
from app import synchronizer

CHANNELS = "channels.list_channels"
MESSAGES = "messages.list_messages"
CHANNELS_URL = "http://channels:8000"
MESSAGES_URL = "http://messages:8000"


def make_sync(repos: Repositories) -> MessageSynchronizer:
    return MessageSynchronizer(CHANNELS_URL, MESSAGES_URL, repos.read_model,
                               repos.leases, "contrato", interval=10)


# --- Lado consumidor --------------------------------------------------------------

def test_el_sincronizador_copia_los_ejemplos_del_contrato(
        contract, static_service, http_bridge, repos, monkeypatch):
    channels, messages = contract(CHANNELS).example, contract(MESSAGES).example
    contract(CHANNELS).assert_valid(channels)
    contract(MESSAGES).assert_valid(messages)
    channel_id = channels[0]["id"]
    http = http_bridge({
        CHANNELS_URL: static_service({"/api/v1/channels": channels}),
        MESSAGES_URL: static_service({f"/api/v1/channels/{channel_id}/messages": messages}),
    })
    monkeypatch.setattr(synchronizer, "urlopen", http.urlopen)
    assert make_sync(repos).sync_all() == 1
    stored = repos.read_model.get(messages[0]["id"])
    assert (stored.channel_id, stored.content) == (channel_id, messages[0]["content"])


# --- Lado proveedor ---------------------------------------------------------------

def test_channels_lista_canales_segun_el_contrato(contract, channels_provider):
    _, client = channels_provider
    client.post("/api/v1/channels", json={"name": "general"})
    client.post("/api/v1/channels", json={"name": "finanzas"})
    response = client.get("/api/v1/channels")
    assert response.status_code == 200
    assert len(response.json()) == 2
    contract(CHANNELS).assert_valid(response.json())


def test_messages_lista_mensajes_segun_el_contrato(contract, messages_provider,
                                                   author_and_channel):
    _, client = messages_provider
    author, channel = author_and_channel
    url = f"/api/v1/channels/{channel['id']}/messages"
    client.post(url, json={"author_id": author["id"], "content": "El deploy quedó listo"})
    response = client.get(url)
    assert response.status_code == 200
    contract(MESSAGES).assert_valid(response.json())


def test_messages_lista_vacia_para_un_canal_sin_mensajes(contract, messages_provider):
    _, client = messages_provider
    response = client.get("/api/v1/channels/sin-mensajes/messages")
    assert response.status_code == 200
    assert response.json() == []
    contract(MESSAGES).assert_valid(response.json())


# --- Proveedores reales + consumidor ----------------------------------------------

def test_el_sincronizador_lee_los_proveedores_reales(
        channels_provider, messages_provider, author_and_channel, http_bridge,
        repos, monkeypatch):
    author, channel = author_and_channel
    created = messages_provider[1].post(
        f"/api/v1/channels/{channel['id']}/messages",
        json={"author_id": author["id"], "content": "Revisen el KPI"}).json()
    http = http_bridge({CHANNELS_URL: channels_provider[1],
                        MESSAGES_URL: messages_provider[1]})
    monkeypatch.setattr(synchronizer, "urlopen", http.urlopen)
    assert make_sync(repos).sync_all() == 1
    assert repos.read_model.get(created["id"]).content == "Revisen el KPI"
