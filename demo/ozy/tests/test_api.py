from app import main, publisher


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seed_is_loaded_and_idempotent(client, repos):
    from app.seed import seed_glossary
    seed_glossary(repos.glossary)
    assert len(client.get("/api/v1/glossary").json()) == 17


# --- Traducción ---------------------------------------------------------------

def test_translation_of_unknown_message_is_404(client):
    response = client.post("/api/v1/messages/nope/translation")
    assert response.status_code == 404
    assert response.json()["detail"] == "Message not found"


def test_create_translation(client, message):
    response = client.post("/api/v1/messages/m1/translation")
    assert response.status_code == 201
    body = response.json()
    assert body["audience_level"] == "basico"
    assert [(t["term"], t["known"], t["ambiguous"]) for t in body["terms"]] == [
        ("PR", True, True), ("Pipeline", True, False),
        ("KPI", True, False), ("ETL", False, False)]
    assert "significa cosas distintas" in body["explanation"]


def test_create_translation_registers_candidates_once(client, message):
    client.post("/api/v1/messages/m1/translation")
    client.post("/api/v1/messages/m1/translation")
    candidates = client.get("/api/v1/glossary?estado=candidato").json()
    assert [entry["term"] for entry in candidates] == ["ETL"]


def test_create_translation_publishes_event(client, message):
    translation = client.post("/api/v1/messages/m1/translation",
                              json={"audience_level": "experto"}).json()
    [event] = client.get("/api/v1/events").json()
    assert event["type"] == "chat.translation.created"
    assert event["data"] == {"translation_id": translation["translation_id"],
                             "message_id": "m1", "channel_id": "c1",
                             "audience_level": "experto",
                             "terms": ["PR", "Pipeline", "KPI", "ETL"]}


def test_translation_is_replaced_per_audience_level(client, repos, message):
    client.post("/api/v1/messages/m1/translation")
    client.post("/api/v1/messages/m1/translation")
    client.post("/api/v1/messages/m1/translation", json={"audience_level": "intermedio"})
    assert repos.translations.collection.count_documents({}) == 2


def test_invalid_audience_level_is_422(client, message):
    response = client.post("/api/v1/messages/m1/translation", json={"audience_level": "x"})
    assert response.status_code == 422


def test_get_translation_includes_author_name(client, message, monkeypatch):
    monkeypatch.setattr(main, "get_display_name", lambda author_id: "Ana")
    created = client.post("/api/v1/messages/m1/translation").json()
    body = client.get("/api/v1/messages/m1/translation").json()
    assert body["translation_id"] == created["translation_id"]
    assert body["author"] == {"id": "a1", "display_name": "Ana"}


def test_get_translation_works_when_users_is_down(client, message):
    client.post("/api/v1/messages/m1/translation")
    response = client.get("/api/v1/messages/m1/translation")
    assert response.status_code == 200
    assert response.json()["author"] == {"id": "a1", "display_name": None}


def test_get_missing_translation_is_404(client, message):
    response = client.get("/api/v1/messages/m1/translation?audience_level=experto")
    assert response.status_code == 404


# --- Glosario -----------------------------------------------------------------

def test_glossary_filters(client):
    marketing = client.get("/api/v1/glossary?ambito=marketing").json()
    assert [entry["term"] for entry in marketing] == ["CAC", "Funnel", "Lead", "PR"]
    assert "term_normalized" not in marketing[0]
    assert client.get("/api/v1/glossary?estado=validado").json()
    assert client.get("/api/v1/glossary?ambito=astrologia").status_code == 422


def test_get_term_returns_all_entries_by_ambito(client):
    body = client.get("/api/v1/glossary/pr").json()
    assert body["term"] == "PR" and body["ambiguous"]
    assert [entry["ambito"] for entry in body["entries"]] == ["finanzas", "marketing", "software"]
    assert client.get("/api/v1/glossary/inexistente").status_code == 404


# --- Validación ---------------------------------------------------------------

def candidate_id(client, message):
    client.post("/api/v1/messages/m1/translation")
    return client.get("/api/v1/glossary/ETL").json()["entries"][0]["id"]


def test_validate_candidate_with_definition(client, message):
    entry_id = candidate_id(client, message)
    response = client.patch(f"/api/v1/glossary/{entry_id}/validation", json={
        "estado": "validado", "validated_by": "u1", "ambito": "datos",
        "definition": "Proceso que extrae, transforma y carga datos."})
    assert response.status_code == 200
    body = response.json()
    assert (body["estado"], body["ambito"], body["validated_by"]) == ("validado", "datos", "u1")
    assert body["validated_at"]
    etl = client.post("/api/v1/messages/m1/translation").json()["terms"][-1]
    assert etl["term"] == "ETL" and etl["known"]


def test_validating_without_definition_is_422(client, message):
    entry_id = candidate_id(client, message)
    response = client.patch(f"/api/v1/glossary/{entry_id}/validation",
                            json={"estado": "validado", "validated_by": "u1"})
    assert response.status_code == 422


def test_reject_definition(client):
    entry_id = client.get("/api/v1/glossary/PR").json()["entries"][1]["id"]
    response = client.patch(f"/api/v1/glossary/{entry_id}/validation",
                            json={"estado": "rechazado", "validated_by": "u2"})
    assert response.json()["estado"] == "rechazado"
    assert client.get("/api/v1/glossary/PR").json()["ambiguous"]  # quedan 2 ámbitos


def test_validation_rejects_bad_requests(client):
    entry_id = client.get("/api/v1/glossary/KPI").json()["entries"][0]["id"]
    url = f"/api/v1/glossary/{entry_id}/validation"
    assert client.patch(url, json={"estado": "candidato", "validated_by": "u"}).status_code == 422
    assert client.patch(url, json={"estado": "validado"}).status_code == 422
    assert client.patch("/api/v1/glossary/nope/validation",
                        json={"estado": "rechazado", "validated_by": "u"}).status_code == 404


def test_validation_conflict_when_ambito_already_defined(client, repos):
    repos.glossary.add_candidate("KPI")
    entries = client.get("/api/v1/glossary/KPI").json()["entries"]
    candidate = next(entry for entry in entries if entry["estado"] == "candidato")
    response = client.patch(f"/api/v1/glossary/{candidate['id']}/validation", json={
        "estado": "validado", "validated_by": "u1", "ambito": "datos", "definition": "x"})
    assert response.status_code == 409


def test_events_is_a_flat_list(client):
    publisher.events.clear()
    assert client.get("/api/v1/events").json() == []
