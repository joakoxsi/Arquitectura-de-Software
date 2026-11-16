"""Pruebas de servicio de la API de Ozy: al menos dos por endpoint, una de ellas de error.

Cada clase corresponde a un endpoint. Se ejercita la app FastAPI completa (rutas,
validación, repositorios y eventos) con TestClient, sobre la BD de pruebas de
`conftest.py`: se crea por test, se inyecta con `app.dependency_overrides` y se
destruye al terminar. El broker y el servicio `users` están simulados.

Ozy no tiene autenticación, así que los casos de error son de entrada inválida,
recurso inexistente, conflicto o método no permitido.
"""
from unittest.mock import MagicMock

from pymongo.errors import ServerSelectionTimeoutError

from app import main

GLOSSARY = "/api/v1/glossary"
EVENTS = "/api/v1/events"


def translation_url(message_id: str = "m1") -> str:
    return f"/api/v1/messages/{message_id}/translation"


def validation_url(entry_id: str) -> str:
    return f"{GLOSSARY}/{entry_id}/validation"


def candidate_id(client) -> str:
    """Traduce el mensaje de prueba y devuelve el id del candidato ETL que registra."""
    client.post(translation_url())
    return client.get(f"{GLOSSARY}/ETL").json()["entries"][0]["id"]


def event_types(client) -> list[str]:
    return [event["type"] for event in client.get(EVENTS).json()]


# --- GET /health ----------------------------------------------------------------

class TestHealth:
    def test_responde_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_indica_la_replica_que_respondio(self, client):
        response = client.get("/health")
        assert response.headers["X-Ozy-Instance"] == main.INSTANCE

    def test_error_metodo_no_permitido(self, client):
        assert client.post("/health").status_code == 405


# --- GET /health/live -----------------------------------------------------------

class TestLiveness:
    def test_ok_sin_consumidor(self, client):
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_ok_con_consumidor_vivo(self, client, monkeypatch):
        alive = MagicMock()
        alive.is_alive.return_value = True
        monkeypatch.setattr(main, "consumer", alive)
        assert client.get("/health/live").status_code == 200

    def test_error_503_si_el_hilo_consumidor_murio(self, client, monkeypatch):
        dead = MagicMock()
        dead.is_alive.return_value = False
        monkeypatch.setattr(main, "consumer", dead)
        response = client.get("/health/live")
        assert response.status_code == 503
        assert response.json()["consumer"] == "dead"


# --- GET /health/ready ----------------------------------------------------------

class TestReadiness:
    def test_ok_si_mongo_responde(self, client):
        response = client.get("/health/ready")
        assert response.status_code == 200
        body = response.json()
        assert (body["mongodb"], body["consumer"], body["ingestion"]) == \
            ("ok", "disabled", "disabled")

    def test_error_503_si_mongo_esta_caido(self, client, repos, monkeypatch):
        def down(*_args, **_kwargs):
            raise ServerSelectionTimeoutError("no servers")
        monkeypatch.setattr(repos.glossary.collection.database, "command", down)
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["mongodb"] == "ServerSelectionTimeoutError"


# --- POST /api/v1/messages/{message_id}/translation -----------------------------

class TestCreateTranslation:
    def test_crea_la_traduccion_basica_por_defecto(self, client, message):
        response = client.post(translation_url())
        assert response.status_code == 201
        body = response.json()
        assert body["audience_level"] == "basico"
        assert [(t["term"], t["known"], t["ambiguous"]) for t in body["terms"]] == [
            ("PR", True, True), ("Pipeline", True, False),
            ("KPI", True, False), ("ETL", False, False)]
        assert "significa cosas distintas" in body["explanation"]

    def test_publica_chat_translation_created(self, client, message):
        translation = client.post(translation_url(),
                                  json={"audience_level": "experto"}).json()
        candidate, event = client.get(EVENTS).json()
        assert candidate["type"] == "chat.glossary.candidate.registered"
        assert event["type"] == "chat.translation.created"
        assert event["subject_id"] == translation["translation_id"]
        assert event["data"] == {"translation_id": translation["translation_id"],
                                 "message_id": "m1", "channel_id": "c1",
                                 "audience_level": "experto",
                                 "terms": ["PR", "Pipeline", "KPI", "ETL"]}

    def test_registra_cada_candidato_una_sola_vez(self, client, message):
        client.post(translation_url())
        client.post(translation_url())
        candidates = client.get(f"{GLOSSARY}?estado=candidato").json()
        assert [entry["term"] for entry in candidates] == ["ETL"]
        assert event_types(client) == ["chat.glossary.candidate.registered",
                                       "chat.translation.created",
                                       "chat.translation.created"]
        [candidate] = [e for e in client.get(EVENTS).json()
                       if e["type"] == "chat.glossary.candidate.registered"]
        assert candidate["data"] == {"entry_id": candidates[0]["id"], "term": "ETL",
                                     "message_id": "m1", "channel_id": "c1"}

    def test_hay_una_traduccion_por_mensaje_y_nivel(self, client, repos, message):
        client.post(translation_url())
        client.post(translation_url())
        client.post(translation_url(), json={"audience_level": "intermedio"})
        assert repos.translations.collection.count_documents({}) == 2

    def test_error_404_mensaje_inexistente_y_sin_eventos(self, client):
        response = client.post(translation_url("nope"))
        assert response.status_code == 404
        assert response.json()["detail"] == "Message not found"
        assert client.get(EVENTS).json() == []

    def test_error_422_nivel_de_audiencia_invalido(self, client, message):
        response = client.post(translation_url(), json={"audience_level": "x"})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "audience_level"]

    def test_error_422_cuerpo_que_no_es_un_objeto(self, client, message):
        assert client.post(translation_url(), json=["basico"]).status_code == 422


# --- GET /api/v1/messages/{message_id}/translation ------------------------------

class TestGetTranslation:
    def test_incluye_el_nombre_del_autor(self, client, message, monkeypatch):
        monkeypatch.setattr(main, "get_display_name", lambda author_id: "Ana")
        created = client.post(translation_url()).json()
        response = client.get(translation_url())
        assert response.status_code == 200
        body = response.json()
        assert body["translation_id"] == created["translation_id"]
        assert body["author"] == {"id": "a1", "display_name": "Ana"}

    def test_responde_aunque_users_este_caido(self, client, message):
        client.post(translation_url())
        response = client.get(translation_url())
        assert response.status_code == 200
        assert response.json()["author"] == {"id": "a1", "display_name": None}

    def test_error_404_nivel_no_generado(self, client, message):
        client.post(translation_url())  # solo genera `basico`
        response = client.get(f"{translation_url()}?audience_level=experto")
        assert response.status_code == 404
        assert response.json()["detail"] == "Translation not found"

    def test_error_404_mensaje_inexistente(self, client):
        assert client.get(translation_url("nope")).status_code == 404

    def test_error_422_nivel_invalido(self, client, message):
        response = client.get(f"{translation_url()}?audience_level=avanzado")
        assert response.status_code == 422


# --- GET /api/v1/glossary -------------------------------------------------------

class TestListGlossary:
    def test_lista_el_glosario_inicial_sin_duplicar_el_seed(self, client, repos):
        from app.seed import seed_glossary
        seed_glossary(repos.glossary)  # el lifespan ya lo cargó: es idempotente
        entries = client.get(GLOSSARY).json()
        assert len(entries) == 17
        assert "term_normalized" not in entries[0]

    def test_filtra_por_ambito_y_estado(self, client):
        marketing = client.get(f"{GLOSSARY}?ambito=marketing").json()
        assert [entry["term"] for entry in marketing] == ["CAC", "Funnel", "Lead", "PR"]
        assert len(client.get(f"{GLOSSARY}?estado=validado").json()) == 17
        assert client.get(f"{GLOSSARY}?estado=candidato").json() == []

    def test_error_422_ambito_inexistente(self, client):
        response = client.get(f"{GLOSSARY}?ambito=astrologia")
        assert response.status_code == 422

    def test_error_422_estado_inexistente(self, client):
        assert client.get(f"{GLOSSARY}?estado=aprobado").status_code == 422


# --- GET /api/v1/glossary/{term} ------------------------------------------------

class TestGetTerm:
    def test_devuelve_todas_las_entradas_por_ambito(self, client):
        body = client.get(f"{GLOSSARY}/pr").json()  # no distingue mayúsculas
        assert body["term"] == "PR" and body["ambiguous"]
        assert [entry["ambito"] for entry in body["entries"]] == \
            ["finanzas", "marketing", "software"]

    def test_termino_con_un_solo_ambito_no_es_ambiguo(self, client):
        body = client.get(f"{GLOSSARY}/KPI").json()
        assert not body["ambiguous"]
        assert [entry["ambito"] for entry in body["entries"]] == ["datos"]

    def test_error_404_termino_inexistente(self, client):
        response = client.get(f"{GLOSSARY}/inexistente")
        assert response.status_code == 404
        assert response.json()["detail"] == "Term not found"


# --- PATCH /api/v1/glossary/{entry_id}/validation -------------------------------

class TestValidateEntry:
    def test_valida_un_candidato_con_definicion(self, client, message):
        entry_id = candidate_id(client)
        response = client.patch(validation_url(entry_id), json={
            "estado": "validado", "validated_by": "u1", "ambito": "datos",
            "definition": "Proceso que extrae, transforma y carga datos."})
        assert response.status_code == 200
        body = response.json()
        assert (body["estado"], body["ambito"], body["validated_by"]) == \
            ("validado", "datos", "u1")
        assert body["validated_at"]
        etl = client.post(translation_url()).json()["terms"][-1]
        assert etl["term"] == "ETL" and etl["known"]

    def test_rechaza_una_definicion(self, client):
        entry_id = client.get(f"{GLOSSARY}/PR").json()["entries"][1]["id"]
        response = client.patch(validation_url(entry_id),
                                json={"estado": "rechazado", "validated_by": "u2"})
        assert response.status_code == 200
        assert response.json()["estado"] == "rechazado"
        assert client.get(f"{GLOSSARY}/PR").json()["ambiguous"]  # quedan 2 ámbitos

    def test_validar_y_rechazar_emiten_eventos(self, client, message):
        entry_id = candidate_id(client)
        client.patch(validation_url(entry_id), json={
            "estado": "validado", "validated_by": "u1", "ambito": "datos",
            "definition": "x"})
        pr_id = client.get(f"{GLOSSARY}/PR").json()["entries"][0]["id"]
        client.patch(validation_url(pr_id),
                     json={"estado": "rechazado", "validated_by": "u2"})
        validated, rejected = client.get(EVENTS).json()[-2:]
        assert validated["type"] == "chat.glossary.entry.validated"
        assert validated["data"] == {"entry_id": entry_id, "term": "ETL",
                                     "ambito": "datos", "estado": "validado",
                                     "validated_by": "u1"}
        assert rejected["type"] == "chat.glossary.entry.rejected"
        assert rejected["subject_id"] == pr_id

    def test_error_404_entrada_inexistente_y_sin_eventos(self, client):
        response = client.patch(validation_url("nope"),
                                json={"estado": "rechazado", "validated_by": "u"})
        assert response.status_code == 404
        assert response.json()["detail"] == "Glossary entry not found"
        assert client.get(EVENTS).json() == []

    def test_error_422_validar_candidato_sin_definicion(self, client, message):
        entry_id = candidate_id(client)
        response = client.patch(validation_url(entry_id),
                                json={"estado": "validado", "validated_by": "u1"})
        assert response.status_code == 422
        assert response.json()["detail"] == \
            "A validated entry needs a definition and an ambito"

    def test_error_422_cuerpo_invalido(self, client):
        entry_id = client.get(f"{GLOSSARY}/KPI").json()["entries"][0]["id"]
        url = validation_url(entry_id)
        assert client.patch(url, json={"estado": "candidato",
                                       "validated_by": "u"}).status_code == 422
        assert client.patch(url, json={"estado": "validado"}).status_code == 422
        assert client.patch(url, json={"estado": "validado",
                                       "validated_by": ""}).status_code == 422
        assert client.patch(url, json={"estado": "validado", "validated_by": "u",
                                       "ambito": "astrologia"}).status_code == 422

    def test_error_409_ambito_ya_definido_para_el_termino(self, client, repos):
        repos.glossary.add_candidate("KPI")
        entries = client.get(f"{GLOSSARY}/KPI").json()["entries"]
        candidate = next(entry for entry in entries if entry["estado"] == "candidato")
        response = client.patch(validation_url(candidate["id"]), json={
            "estado": "validado", "validated_by": "u1", "ambito": "datos",
            "definition": "x"})
        assert response.status_code == 409
        assert response.json()["detail"] == "Term already has an entry for that ambito"


# --- GET /api/v1/events ---------------------------------------------------------

class TestEvents:
    def test_lista_vacia_al_arrancar(self, client):
        response = client.get(EVENTS)
        assert response.status_code == 200
        assert response.json() == []

    def test_lista_los_eventos_en_orden_con_el_sobre_comun(self, client, message):
        client.post(translation_url())
        events = client.get(EVENTS).json()
        assert [event["type"] for event in events] == \
            ["chat.glossary.candidate.registered", "chat.translation.created"]
        assert all(set(event) == {"type", "subject_id", "occurred_at", "data"}
                   for event in events)

    def test_error_metodo_no_permitido(self, client):
        assert client.post(EVENTS, json={"type": "x"}).status_code == 405


# --- Aislamiento de la base de datos -------------------------------------------

class TestAislamiento:
    def test_las_rutas_usan_la_bd_de_pruebas_y_no_la_de_ozy(self, client, repos, message):
        client.post(translation_url())
        assert repos.translations.collection.count_documents({}) == 1
        assert main.repos is not repos
        assert main.repos.translations.collection.count_documents({}) == 0
        assert main.repos.events.collection.count_documents({}) == 0

    def test_cada_test_recibe_una_bd_vacia(self, repos):
        assert repos.read_model.collection.count_documents({}) == 0
        assert repos.translations.collection.count_documents({}) == 0
