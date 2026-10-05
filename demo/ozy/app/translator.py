"""Motor de traducción determinista basado en glosario + plantillas (sin LLM)."""
from app.detector import DetectedTerm, detect_terms
from app.domain import (AudienceLevel, GlossaryEntry, ReadMessage, TranslatedTerm,
                        Translation)
from app.repositories import GlossaryRepository

NO_TERMS = {
    AudienceLevel.BASICO: "Este mensaje no usa términos técnicos del glosario: "
                          "se puede leer tal cual.",
    AudienceLevel.INTERMEDIO: "No se detectaron términos del glosario en el mensaje.",
    AudienceLevel.EXPERTO: "Sin términos del glosario.",
}


def _meanings(term: DetectedTerm) -> list[str]:
    return [f"en {entry.ambito.value}, {_sentence(entry.definition)}"
            for entry in term.meanings]


def _sentence(text: str) -> str:
    """Definición sin punto final, para poder encadenarla en una frase."""
    return text.strip().rstrip(".")


def _basico(term: DetectedTerm) -> str:
    if not term.known:
        return (f"«{term.term}»: todavía no está en el glosario. Quedó registrado "
                "para que el equipo lo defina; mientras tanto, pregunta a quien "
                "escribió el mensaje.")
    if term.ambiguous:
        return (f"«{term.term}» significa cosas distintas según el área: "
                f"{'; '.join(_meanings(term))}. Confirma con quien escribió el "
                "mensaje a cuál se refiere.")
    return f"«{term.term}»: {term.meanings[0].definition}"


def _intermedio(term: DetectedTerm) -> str:
    if not term.known:
        return f"{term.term} (sin definición, registrado como candidato)"
    if term.ambiguous:
        return f"{term.term} (ambiguo): {'; '.join(_meanings(term))}."
    entry = term.meanings[0]
    return f"{term.term} ({entry.ambito.value}): {entry.definition}"


def _experto(term: DetectedTerm) -> str:
    if not term.known:
        return f"{term.term} [candidato]"
    ambitos = " | ".join(entry.ambito.value for entry in term.meanings)
    return f"{term.term} [{ambitos}{' — ambiguo' if term.ambiguous else ''}]"


def render_explanation(terms: list[DetectedTerm], level: AudienceLevel) -> str:
    if not terms:
        return NO_TERMS[level]
    if level == AudienceLevel.EXPERTO:
        return "Términos: " + ", ".join(_experto(term) for term in terms) + "."
    if level == AudienceLevel.INTERMEDIO:
        return "Glosario del mensaje:\n" + "\n".join(
            f"- {_intermedio(term)}" for term in terms)
    count = len(terms)
    header = (f"Este mensaje usa {count} término{'s' if count > 1 else ''} "
              f"técnico{'s' if count > 1 else ''}. Explicado en simple:")
    return header + "\n" + "\n".join(f"- {_basico(term)}" for term in terms)


def to_translated_term(term: DetectedTerm) -> TranslatedTerm:
    return TranslatedTerm(
        term=term.term,
        known=term.known,
        ambiguous=term.ambiguous,
        meanings=[{"entry_id": entry.id, "ambito": entry.ambito.value,
                   "definition": entry.definition, "estado": entry.estado.value}
                  for entry in term.meanings])


def translate(message: ReadMessage, level: AudienceLevel,
              glossary: GlossaryRepository) -> tuple[Translation, list[GlossaryEntry]]:
    """Detecta términos, registra candidatos y arma la explicación del mensaje.

    Devuelve la traducción y los candidatos que se crearon en esta llamada.
    """
    detection = detect_terms(message.content, glossary.find_all())
    registered = [entry for entry in map(glossary.add_candidate,
                                         detection.new_candidates) if entry]
    translation = Translation(
        message_id=message.message_id,
        channel_id=message.channel_id,
        audience_level=level,
        explanation=render_explanation(detection.terms, level),
        terms=[to_translated_term(term) for term in detection.terms])
    return translation, registered
