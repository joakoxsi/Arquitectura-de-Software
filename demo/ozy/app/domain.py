"""Modelo de dominio de Ozy (lenguaje ubicuo).

Los ids de usuarios, canales y mensajes son referencias externas opacas: se
guardan como strings y nunca se interpretan ni se validan contra otros servicios.
"""
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class Ambito(str, Enum):
    """Contexto donde una definición es válida."""
    SOFTWARE = "software"
    DATOS = "datos"
    PRODUCTO = "producto"
    FINANZAS = "finanzas"
    MARKETING = "marketing"
    OPERACIONES = "operaciones"
    DOMINIO = "dominio"


class Estado(str, Enum):
    CANDIDATO = "candidato"
    VALIDADO = "validado"
    RECHAZADO = "rechazado"


class AudienceLevel(str, Enum):
    BASICO = "basico"
    INTERMEDIO = "intermedio"
    EXPERTO = "experto"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_term(term: str) -> str:
    """Clave de comparación de un término: sin espacios extremos y sin mayúsculas."""
    return " ".join(term.split()).casefold()


class GlossaryEntry(BaseModel):
    """Entrada de glosario: un término con una definición en un ámbito.

    Un mismo término puede tener varias entradas con distinto ámbito; así se
    modela la ambigüedad (ej. "PR"). Un candidato detectado automáticamente aún
    no tiene definición ni ámbito.
    """
    id: str = Field(default_factory=lambda: str(uuid4()))
    term: str = Field(min_length=1, max_length=80)
    term_normalized: str = ""
    definition: str | None = None
    ambito: Ambito | None = None
    estado: Estado = Estado.CANDIDATO
    created_at: str = Field(default_factory=now)
    validated_by: str | None = None
    validated_at: str | None = None

    def model_post_init(self, __context) -> None:
        self.term_normalized = normalize_term(self.term)


class ReadMessage(BaseModel):
    """Copia local (read-model) de un mensaje del chat, en el modelo de Ozy."""
    message_id: str
    channel_id: str
    author_id: str
    content: str
    received_at: str = Field(default_factory=now)


class TranslatedTerm(BaseModel):
    """Término detectado en un mensaje, con sus significados conocidos."""
    term: str
    known: bool
    ambiguous: bool
    meanings: list[dict]


class Translation(BaseModel):
    """Explicación en simple de un mensaje para un nivel de audiencia."""
    translation_id: str = Field(default_factory=lambda: str(uuid4()))
    message_id: str
    channel_id: str
    audience_level: AudienceLevel
    explanation: str
    terms: list[TranslatedTerm]
    created_at: str = Field(default_factory=now)
