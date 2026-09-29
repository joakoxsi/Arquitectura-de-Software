"""Detección de términos técnicos en el contenido de un mensaje."""
import re
from dataclasses import dataclass, field

from app.domain import Estado, GlossaryEntry, normalize_term

# Siglas en mayúsculas de 2 a 6 caracteres que empiezan con letra (ETL, B2B, OKR).
ACRONYM = re.compile(r"(?<!\w)[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9]{1,5}(?!\w)")
# Mayúsculas frecuentes en un chat que no son jerga.
NOT_JARGON = {"ok", "si", "sí", "no", "ya", "ojo", "hola", "tmb", "q", "xd"}


@dataclass
class DetectedTerm:
    term: str
    position: int
    entries: list[GlossaryEntry] = field(default_factory=list)

    @property
    def meanings(self) -> list[GlossaryEntry]:
        """Definiciones utilizables: con texto y no rechazadas."""
        return [entry for entry in self.entries
                if entry.definition and entry.estado != Estado.RECHAZADO]

    @property
    def known(self) -> bool:
        return bool(self.meanings)

    @property
    def ambiguous(self) -> bool:
        return len({entry.ambito for entry in self.meanings}) > 1


@dataclass
class Detection:
    terms: list[DetectedTerm]
    new_candidates: list[str]


def _pattern(term: str) -> re.Pattern:
    """Coincidencia sin distinguir mayúsculas y respetando límites de palabra.

    Se usa (?<!\\w)/(?!\\w) en vez de \\b para soportar términos que terminan en
    símbolos (ej. "C++") y letras acentuadas.
    """
    words = r"\s+".join(re.escape(word) for word in term.split())
    return re.compile(rf"(?<!\w){words}(?!\w)", re.IGNORECASE)


def detect_terms(content: str, glossary: list[GlossaryEntry]) -> Detection:
    """Busca los términos del glosario y propone candidatos para siglas desconocidas.

    `glossary` debe incluir las entradas rechazadas: un término rechazado no se
    muestra como conocido, pero tampoco se vuelve a proponer como candidato.
    """
    by_term: dict[str, list[GlossaryEntry]] = {}
    for entry in glossary:
        by_term.setdefault(entry.term_normalized, []).append(entry)

    found: dict[str, DetectedTerm] = {}
    for normalized, entries in by_term.items():
        if all(entry.estado == Estado.RECHAZADO for entry in entries):
            continue
        match = _pattern(entries[0].term).search(content)
        if match:
            # Se muestra la forma del glosario ("PR"), no la escrita ("pr").
            found[normalized] = DetectedTerm(entries[0].term, match.start(), entries)

    new_candidates: list[str] = []
    for match in ACRONYM.finditer(content):
        normalized = normalize_term(match.group(0))
        if normalized in by_term or normalized in found or normalized in NOT_JARGON:
            continue
        found[normalized] = DetectedTerm(match.group(0), match.start())
        new_candidates.append(match.group(0))

    terms = sorted(found.values(), key=lambda term: term.position)
    return Detection(terms=terms, new_candidates=new_candidates)
