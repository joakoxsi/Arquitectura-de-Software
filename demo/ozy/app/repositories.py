"""Repositorios sobre las colecciones de Ozy."""
from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database

from app.domain import (Ambito, Estado, GlossaryEntry, ReadMessage, Translation,
                        normalize_term, now)

PROJECTION = {"_id": 0}


class ReadModelRepository:
    """messages_read_model: una copia por message_id."""

    def __init__(self, collection: Collection):
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index("message_id", unique=True)

    def upsert(self, message: ReadMessage) -> None:
        """Idempotente: reprocesar el mismo evento no duplica ni cambia received_at."""
        data = message.model_dump()
        received_at = data.pop("received_at")
        self.collection.update_one(
            {"message_id": message.message_id},
            {"$set": data, "$setOnInsert": {"received_at": received_at}},
            upsert=True)

    def get(self, message_id: str) -> ReadMessage | None:
        doc = self.collection.find_one({"message_id": message_id}, PROJECTION)
        return ReadMessage(**doc) if doc else None


class GlossaryRepository:
    """glossary_entries: una entrada por (término, ámbito)."""

    def __init__(self, collection: Collection):
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index("id", unique=True)
        self.collection.create_index(
            [("term_normalized", ASCENDING), ("ambito", ASCENDING)], unique=True)

    def seed(self, entry: GlossaryEntry) -> None:
        """Inserta la entrada si no existe; no pisa validaciones ni rechazos previos."""
        doc = entry.model_dump(mode="json")
        self.collection.update_one(
            {"term_normalized": doc["term_normalized"], "ambito": doc["ambito"]},
            {"$setOnInsert": doc},
            upsert=True)

    def add_candidate(self, term: str) -> None:
        """Registra un término desconocido como candidato, sin duplicarlo."""
        entry = GlossaryEntry(term=term, estado=Estado.CANDIDATO)
        self.collection.update_one(
            {"term_normalized": entry.term_normalized, "ambito": None},
            {"$setOnInsert": entry.model_dump(mode="json")},
            upsert=True)

    def find_all(self, ambito: Ambito | None = None,
                 estado: Estado | None = None) -> list[GlossaryEntry]:
        query = {}
        if ambito is not None:
            query["ambito"] = ambito.value
        if estado is not None:
            query["estado"] = estado.value
        cursor = self.collection.find(query, PROJECTION).sort(
            [("term_normalized", ASCENDING), ("ambito", ASCENDING)])
        return [GlossaryEntry(**doc) for doc in cursor]

    def find_by_term(self, term: str) -> list[GlossaryEntry]:
        cursor = self.collection.find(
            {"term_normalized": normalize_term(term)}, PROJECTION).sort("ambito")
        return [GlossaryEntry(**doc) for doc in cursor]

    def find_not_rejected(self) -> list[GlossaryEntry]:
        """Entradas utilizables para detectar términos (candidatos y validadas)."""
        cursor = self.collection.find(
            {"estado": {"$ne": Estado.RECHAZADO.value}}, PROJECTION)
        return [GlossaryEntry(**doc) for doc in cursor]

    def get(self, entry_id: str) -> GlossaryEntry | None:
        doc = self.collection.find_one({"id": entry_id}, PROJECTION)
        return GlossaryEntry(**doc) if doc else None

    def set_estado(self, entry_id: str, estado: Estado, validated_by: str | None,
                   definition: str | None = None,
                   ambito: Ambito | None = None) -> GlossaryEntry | None:
        """Cambia el estado; opcionalmente completa la definición de un candidato.

        Lanza DuplicateKeyError si el nuevo ámbito ya tiene una entrada del término.
        """
        changes = {"estado": estado.value, "validated_by": validated_by,
                   "validated_at": now()}
        if definition is not None:
            changes["definition"] = definition
        if ambito is not None:
            changes["ambito"] = ambito.value
        self.collection.update_one({"id": entry_id}, {"$set": changes})
        return self.get(entry_id)


class TranslationRepository:
    """translations: una traducción por (message_id, audience_level)."""

    def __init__(self, collection: Collection):
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("message_id", ASCENDING), ("audience_level", ASCENDING)], unique=True)

    def save(self, translation: Translation) -> None:
        """Reemplaza la traducción previa del mismo mensaje y nivel."""
        self.collection.replace_one(
            {"message_id": translation.message_id,
             "audience_level": translation.audience_level.value},
            translation.model_dump(mode="json"),
            upsert=True)

    def get(self, message_id: str, audience_level: str) -> Translation | None:
        doc = self.collection.find_one(
            {"message_id": message_id, "audience_level": audience_level}, PROJECTION)
        return Translation(**doc) if doc else None


class Repositories:
    def __init__(self, database: Database):
        self.read_model = ReadModelRepository(database.messages_read_model)
        self.glossary = GlossaryRepository(database.glossary_entries)
        self.translations = TranslationRepository(database.translations)

    def ensure_indexes(self) -> None:
        self.read_model.ensure_indexes()
        self.glossary.ensure_indexes()
        self.translations.ensure_indexes()
