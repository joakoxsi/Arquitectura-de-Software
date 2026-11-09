import json

import httpx

from tests.conftest import CHANNELS, MESSAGES, OZY, SEARCH, SUMMARIES, USERS

TRANSLATION = {
    "translation_id": "t1", "message_id": "m1", "channel_id": "c1",
    "audience_level": "basico", "explanation": "En simple…", "created_at": "2026-11-09T00:00:00",
    "terms": [{"term": "PR", "known": True, "ambiguous": True, "meanings": [
        {"entry_id": "e1", "ambito": "software", "definition": "Pull Request", "estado": "validado"},
        {"entry_id": "e2", "ambito": "marketing", "definition": "Public Relations",
         "estado": "validado"}]},
        {"term": "ETL", "known": False, "ambiguous": False, "meanings": []}],
}
ENTRY = {"id": "e9", "term": "ETL", "definition": "Extrae, transforma y carga.",
         "ambito": "datos", "estado": "validado", "created_at": "2026-11-09",
         "validated_by": "u1", "validated_at": "2026-11-09"}


def sent_json(route) -> dict:
    return json.loads(route.calls.last.request.content)


# --- Queries ------------------------------------------------------------------

def test_channels(mock, gql):
    mock.get(f"{CHANNELS}/channels").respond(json=[{"id": "c1", "name": "general"}])
    assert gql("{ channels { id name } }") == {
        "data": {"channels": [{"id": "c1", "name": "general"}]}}


def test_messages_are_sorted_and_include_author_name(mock, gql):
    mock.get(f"{MESSAGES}/channels/c1/messages").respond(json=[
        {"id": "m2", "channel_id": "c1", "author_id": "u1", "content": "b",
         "created_at": "2026-11-09T10:00:00"},
        {"id": "m1", "channel_id": "c1", "author_id": "u1", "content": "a",
         "created_at": "2026-11-09T09:00:00"}])
    users = mock.get(f"{USERS}/users/u1").respond(json={"id": "u1", "display_name": "Ana"})
    body = gql("query($c: ID!) { messages(channelId: $c) { id authorName } }", c="c1")
    assert body["data"]["messages"] == [{"id": "m1", "authorName": "Ana"},
                                        {"id": "m2", "authorName": "Ana"}]
    assert users.call_count == 1  # un autor repetido se consulta una sola vez


def test_nested_query_combines_three_services(mock, gql):
    mock.get(f"{CHANNELS}/channels/c1").respond(json={"id": "c1", "name": "general"})
    mock.get(f"{MESSAGES}/channels/c1/messages").respond(json=[
        {"id": "m1", "channel_id": "c1", "author_id": "u1", "content": "El PR",
         "created_at": "t"}])
    mock.get(f"{USERS}/users/u1").respond(json={"id": "u1", "display_name": "Ana"})
    mock.get(f"{OZY}/messages/m1/translation").respond(json=TRANSLATION)
    body = gql("""{ channel(id: "c1") { name messages {
        content author { displayName } translation { terms { term ambiguous } } } } }""")
    assert body["data"]["channel"] == {"name": "general", "messages": [{
        "content": "El PR", "author": {"displayName": "Ana"},
        "translation": {"terms": [{"term": "PR", "ambiguous": True},
                                  {"term": "ETL", "ambiguous": False}]}}]}


def test_message_without_translation_returns_null(mock, gql):
    mock.get(f"{MESSAGES}/channels/c1/messages").respond(json=[
        {"id": "m1", "channel_id": "c1", "author_id": "u1", "content": "x", "created_at": "t"}])
    mock.get(f"{USERS}/users/u1").respond(json={"id": "u1", "display_name": "Ana"})
    mock.get(f"{OZY}/messages/m1/translation").respond(404, json={"detail": "Translation not found"})
    body = gql('{ messages(channelId: "c1") { translation { explanation } } }')
    assert body == {"data": {"messages": [{"translation": None}]}}


def test_translation_with_author(mock, gql):
    route = mock.get(f"{OZY}/messages/m1/translation").respond(
        json={**TRANSLATION, "audience_level": "experto",
              "author": {"id": "u1", "display_name": "Ana"}})
    body = gql('{ translation(messageId: "m1", audienceLevel: experto) '
               '{ audienceLevel author { displayName } terms { meanings { ambito } } } }')
    assert route.calls.last.request.url.params["audience_level"] == "experto"
    assert body["data"]["translation"]["audienceLevel"] == "experto"
    assert body["data"]["translation"]["author"] == {"displayName": "Ana"}


def test_glossary_filters_and_term(mock, gql):
    route = mock.get(f"{OZY}/glossary").respond(json=[ENTRY])
    body = gql("{ glossary(ambito: datos, estado: validado) { term ambito estado } }")
    assert dict(route.calls.last.request.url.params) == {"ambito": "datos", "estado": "validado"}
    assert body["data"]["glossary"] == [{"term": "ETL", "ambito": "datos", "estado": "validado"}]

    mock.get(f"{OZY}/glossary/PR").respond(json={"term": "PR", "ambiguous": True, "entries": [
        {**ENTRY, "term": "PR", "ambito": "software"}, {**ENTRY, "term": "PR", "ambito": None,
                                                        "estado": "candidato"}]})
    body = gql('{ term(term: "PR") { ambiguous entries { ambito estado } } }')
    assert body["data"]["term"] == {"ambiguous": True, "entries": [
        {"ambito": "software", "estado": "validado"}, {"ambito": None, "estado": "candidato"}]}


def test_search_forwards_filters_and_adds_names(mock, gql):
    route = mock.get(f"{SEARCH}/channels/c1/messages/search").respond(json={
        "total_results": 1, "messages": [{
            "id": "m1", "channel_id": "c1", "author_id": "u1", "content": "deploy",
            "created_at": "t", "has": ["link", "mention"], "mentions": ["u2"],
            "links": ["https://x.cl"], "highlights": ["**deploy**"]}]})
    mock.get(f"{USERS}/users/u1").respond(json={"id": "u1", "display_name": "Ana"})
    mock.get(f"{CHANNELS}/channels").respond(json=[{"id": "c1", "name": "general"}])
    body = gql("""{ searchMessages(content: "deploy", channelId: "c1", authorIds: ["u1", "u2"],
        mentions: ["u2"], has: [link], sortBy: relevance, limit: 5) {
        ready totalResults messages { authorName channelName mentions links highlights } } }""")
    params = route.calls.last.request.url.params
    assert params.get_list("author_id") == ["u1", "u2"]
    assert params.get_list("mentions") == ["u2"]
    assert (params["content"], params["has"], params["sort_by"], params["limit"]) == \
        ("deploy", "link", "relevance", "5")
    assert body["data"]["searchMessages"] == {"ready": True, "totalResults": 1, "messages": [
        {"authorName": "Ana", "channelName": "general", "mentions": ["u2"],
         "links": ["https://x.cl"], "highlights": ["**deploy**"]}]}


def test_search_while_index_is_building(mock, gql):
    mock.get(f"{SEARCH}/search/messages").respond(202, json={"detail": "indexing"},
                                                  headers={"Retry-After": "3"})
    body = gql("{ searchMessages { ready retryAfter totalResults } }")
    assert body["data"]["searchMessages"] == {"ready": False, "retryAfter": 3, "totalResults": 0}


def test_summaries(mock, gql):
    mock.get(f"{SUMMARIES}/summaries/s1").respond(json={
        "id": "s1", "channel_id": "c1", "requested_by": "u1", "messageState": "completada",
        "timeInterval": {"start": "a", "end": "b"}, "content": "…", "error": None,
        "created_at": "t", "updated_at": "t",
        "structured": {"overview": "Se decidió X", "decisions": ["X"],
                       "events": [{"description": "Demo", "when": "viernes"}],
                       "tasks": [{"description": "Deploy", "assignee": None}]}})
    body = gql('{ summary(id: "s1") { messageState timeInterval { start } '
               'structured { overview events { when } tasks { assignee } } } }')
    assert body["data"]["summary"] == {
        "messageState": "completada", "timeInterval": {"start": "a"},
        "structured": {"overview": "Se decidió X", "events": [{"when": "viernes"}],
                       "tasks": [{"assignee": None}]}}


def test_health(mock, gql):
    for url in ["users", "channels", "messages", "ozy", "summaries"]:
        mock.get(f"http://{url}:8000/health").respond(json={"status": "ok"})
    mock.get("http://search:8000/health").mock(side_effect=httpx.ConnectError("down"))
    statuses = {s["service"]: s["status"]
                for s in gql("{ health { service status } }")["data"]["health"]}
    assert statuses["ozy"] == "ok" and statuses["search"] == "down"


# --- Mutaciones ---------------------------------------------------------------

def test_create_user_and_channel(mock, gql):
    users = mock.post(f"{USERS}/users").respond(201, json={"id": "u1", "display_name": "Ana"})
    mock.post(f"{CHANNELS}/channels").respond(201, json={"id": "c1", "name": "equipo"})
    body = gql('mutation { createUser(displayName: "Ana") { id displayName } '
               'createChannel(name: "equipo") { id name } }')
    assert sent_json(users) == {"display_name": "Ana"}
    assert body["data"] == {"createUser": {"id": "u1", "displayName": "Ana"},
                            "createChannel": {"id": "c1", "name": "equipo"}}


def test_send_message_reuses_cached_author_name(mock, gql):
    mock.post(f"{USERS}/users").respond(201, json={"id": "u1", "display_name": "Ana"})
    route = mock.post(f"{MESSAGES}/channels/c1/messages").respond(201, json={
        "id": "m1", "channel_id": "c1", "author_id": "u1", "content": "El PR",
        "created_at": "t"})
    users_get = mock.get(f"{USERS}/users/u1")
    gql('mutation { createUser(displayName: "Ana") { id } }')
    body = gql('mutation($c: ID!, $a: ID!, $t: String!) { sendMessage(channelId: $c, '
               'authorId: $a, content: $t) { id authorName } }', c="c1", a="u1", t="El PR")
    assert sent_json(route) == {"author_id": "u1", "content": "El PR"}
    assert body["data"]["sendMessage"] == {"id": "m1", "authorName": "Ana"}
    assert users_get.call_count == 0


def test_translate_message(mock, gql):
    route = mock.post(f"{OZY}/messages/m1/translation").respond(201, json=TRANSLATION)
    body = gql('mutation { translateMessage(messageId: "m1", audienceLevel: intermedio, '
               'channelId: "c1") { translationId terms { term known meanings { ambito } } } }')
    assert sent_json(route) == {"audience_level": "intermedio"}
    assert route.calls.last.request.url.params["channel_id"] == "c1"
    assert body["data"]["translateMessage"]["terms"][0] == {
        "term": "PR", "known": True,
        "meanings": [{"ambito": "software"}, {"ambito": "marketing"}]}


def test_validate_glossary_entry(mock, gql):
    route = mock.patch(f"{OZY}/glossary/e9/validation").respond(json=ENTRY)
    body = gql('mutation { validateGlossaryEntry(entryId: "e9", estado: validado, '
               'validatedBy: "u1", ambito: datos, definition: "Extrae, transforma y carga.") '
               '{ estado validatedBy } }')
    assert sent_json(route) == {"estado": "validado", "validated_by": "u1", "ambito": "datos",
                                "definition": "Extrae, transforma y carga."}
    assert body["data"]["validateGlossaryEntry"] == {"estado": "validado", "validatedBy": "u1"}


def test_request_summary(mock, gql):
    route = mock.post(f"{SUMMARIES}/channels/c1/summaries").respond(
        202, json={"summary_id": "s1", "messageState": "pendiente"})
    body = gql('mutation { requestSummary(channelId: "c1", userId: "u1", '
               'timeInterval: {start: "a", end: "b"}) { summaryId messageState } }')
    assert sent_json(route) == {"user_id": "u1", "timeInterval": {"start": "a", "end": "b"}}
    assert body["data"]["requestSummary"] == {"summaryId": "s1", "messageState": "pendiente"}


def test_request_summary_without_arguments_sends_empty_object(mock, gql):
    """summaries documenta el cuerpo como objeto JSON: nunca se envía sin cuerpo."""
    route = mock.post(f"{SUMMARIES}/channels/c1/summaries").respond(
        202, json={"summary_id": "s2", "messageState": "pendiente"})
    body = gql('mutation { requestSummary(channelId: "c1") { summaryId } }')
    assert sent_json(route) == {}
    assert body["data"]["requestSummary"] == {"summaryId": "s2"}


def test_latest_summary(mock, gql):
    mock.get(f"{SUMMARIES}/channels/c1/summaries/latest").respond(json={
        "id": "s1", "channel_id": "c1", "requested_by": None, "messageState": "completada",
        "timeInterval": None, "content": "…", "error": None, "structured": None,
        "created_at": "t", "updated_at": "t"})
    body = gql('{ latestSummary(channelId: "c1") { id messageState } }')
    assert body["data"]["latestSummary"] == {"id": "s1", "messageState": "completada"}


def test_latest_summary_is_null_when_there_is_none(mock, gql):
    mock.get(f"{SUMMARIES}/channels/c1/summaries/latest").respond(
        404, json={"detail": "No completed summary"})
    body = gql('{ latestSummary(channelId: "c1") { id } }')
    assert body == {"data": {"latestSummary": None}}


def test_latest_summary_other_errors_are_not_hidden(mock, gql):
    mock.get(f"{SUMMARIES}/channels/c1/summaries/latest").respond(
        503, json={"detail": "Summary storage unavailable"})
    body = gql('{ latestSummary(channelId: "c1") { id } }')
    # El campo es anulable: data trae null, pero el error se informa igual.
    assert body["data"] == {"latestSummary": None}
    [error] = body["errors"]
    assert error["extensions"] == {"code": "SERVICE_UNAVAILABLE", "status": 503}
    assert error["path"] == ["latestSummary"]


# --- Errores ------------------------------------------------------------------

def test_service_error_keeps_status_and_detail(mock, gql):
    mock.post(f"{OZY}/messages/nope/translation").respond(404, json={"detail": "Message not found"})
    body = gql('mutation { translateMessage(messageId: "nope") { translationId } }')
    assert body["data"] is None
    [error] = body["errors"]
    assert error["message"] == "Message not found"
    assert error["extensions"] == {"code": "NOT_FOUND", "status": 404}
    assert error["path"] == ["translateMessage"]


def test_unreachable_service_is_503(mock, gql):
    mock.get(f"{CHANNELS}/channels").mock(side_effect=httpx.ConnectError("down"))
    [error] = gql("{ channels { id } }")["errors"]
    assert error["extensions"] == {"code": "SERVICE_UNAVAILABLE", "status": 503}


def test_invalid_enum_is_rejected_before_calling_services(mock, gql):
    route = mock.post(f"{OZY}/messages/m1/translation")
    body = gql('mutation { translateMessage(messageId: "m1", audienceLevel: avanzado) '
               '{ translationId } }')
    assert "avanzado" in body["errors"][0]["message"]
    assert route.call_count == 0


def test_graphiql_is_served(client):
    response = client.get("/graphql", headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert "graphiql" in response.text.lower()
