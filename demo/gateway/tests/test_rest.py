"""La API REST anterior sigue funcionando sobre el mismo módulo de servicios."""
from tests.conftest import CHANNELS, MESSAGES, SEARCH, SUMMARIES, USERS


def test_list_messages_with_author_name(mock, client):
    mock.get(f"{MESSAGES}/channels/c1/messages").respond(json=[
        {"id": "m1", "channel_id": "c1", "author_id": "u1", "content": "a", "created_at": "t"}])
    mock.get(f"{USERS}/users/u1").respond(json={"id": "u1", "display_name": "Ana"})
    assert client.get("/api/channels/c1/messages").json()[0]["author_name"] == "Ana"


def test_service_error_is_propagated(mock, client):
    mock.get(f"{CHANNELS}/channels/x").respond(404, json={"detail": "Channel not found"})
    response = client.get("/api/channels/x")
    assert (response.status_code, response.json()) == (404, {"detail": "Channel not found"})


def test_invalid_json_body_is_400(client):
    response = client.post("/api/users", content=b"{no json",
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_search_202_is_passed_through(mock, client):
    mock.get(f"{SEARCH}/search/messages").respond(202, json={}, headers={"Retry-After": "4"})
    response = client.get("/api/search/messages")
    assert (response.status_code, response.headers["retry-after"]) == (202, "4")


def test_request_summary_without_body_sends_empty_object(mock, client):
    route = mock.post(f"{SUMMARIES}/channels/c1/summaries").respond(
        202, json={"summary_id": "s1", "messageState": "pendiente"})
    response = client.post("/api/channels/c1/summaries")
    assert response.status_code == 202
    assert route.calls.last.request.content == b"{}"
