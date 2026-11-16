"""Contrato de GET /api/v1/users/{user_id}: lo expone `users` y Ozy lo usa para el autor."""
from app import users_client
from app.config import USERS_URL

NAME = "users.get_user"


# --- Lado consumidor ----------------------------------------------------------------

def test_ozy_lee_display_name_del_ejemplo_del_contrato(contract, static_service,
                                                     http_bridge, monkeypatch):
    example = contract(NAME).example
    contract(NAME).assert_valid(example)  # el ejemplo no puede desviarse del schema
    users = static_service({f"/api/v1/users/{example['id']}": example})
    monkeypatch.setattr(users_client, "urlopen", http_bridge({USERS_URL: users}).urlopen)
    assert users_client.get_display_name(example["id"]) == example["display_name"]


def test_ozy_tolera_campos_nuevos_en_la_respuesta(contract, static_service,
                                                  http_bridge, monkeypatch):
    body = {**contract(NAME).example, "avatar_url": "https://x/a.png", "role": "dev"}
    contract(NAME).assert_valid(body)
    users = static_service({f"/api/v1/users/{body['id']}": body})
    monkeypatch.setattr(users_client, "urlopen", http_bridge({USERS_URL: users}).urlopen)
    assert users_client.get_display_name(body["id"]) == body["display_name"]


# --- Lado proveedor + consumidor contra el `users` real ----------------------------

def test_users_responde_segun_el_contrato(contract, users_provider):
    _, client = users_provider
    created = client.post("/api/v1/users", json={"display_name": "Ana"}).json()
    response = client.get(f"/api/v1/users/{created['id']}")
    assert response.status_code == 200
    contract(NAME).assert_valid(response.json())


def test_users_responde_404_si_el_usuario_no_existe(users_provider):
    _, client = users_provider
    response = client.get("/api/v1/users/no-existe")
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_ozy_obtiene_el_nombre_desde_el_users_real(users_provider, http_bridge, monkeypatch):
    _, client = users_provider
    created = client.post("/api/v1/users", json={"display_name": "Ana"}).json()
    http = http_bridge({USERS_URL: client})
    monkeypatch.setattr(users_client, "urlopen", http.urlopen)
    assert users_client.get_display_name(created["id"]) == "Ana"
    assert http.calls == [f"{USERS_URL}/api/v1/users/{created['id']}"]


def test_ozy_degrada_a_none_con_el_404_real_de_users(users_provider, http_bridge,
                                                    monkeypatch):
    _, client = users_provider
    http = http_bridge({USERS_URL: client})
    monkeypatch.setattr(users_client, "urlopen", http.urlopen)
    assert users_client.get_display_name("no-existe") is None
