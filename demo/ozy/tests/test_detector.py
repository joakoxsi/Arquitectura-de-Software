from app.detector import detect_terms
from app.domain import Ambito, Estado, GlossaryEntry


def entry(term, ambito=Ambito.SOFTWARE, definition="def", estado=Estado.VALIDADO):
    return GlossaryEntry(term=term, ambito=ambito, definition=definition, estado=estado)


GLOSSARY = [
    entry("API"), entry("Deploy"), entry("Time to market", Ambito.PRODUCTO),
    entry("PR"), entry("PR", Ambito.MARKETING), entry("PR", Ambito.FINANZAS),
]


def terms(content, glossary=GLOSSARY):
    return [term.term for term in detect_terms(content, glossary).terms]


def test_is_case_insensitive_and_shows_glossary_form():
    assert terms("hicimos el deploy y la api") == ["Deploy", "API"]


def test_respects_word_boundaries():
    assert terms("las APIs y el redeploy") == []
    assert terms("la API, el Deploy.") == ["API", "Deploy"]


def test_matches_multiword_terms_with_any_spacing():
    assert terms("bajar el time   to Market") == ["Time to market"]


def test_orders_terms_by_first_appearance_without_duplicates():
    assert terms("Deploy de la API y otro deploy") == ["Deploy", "API"]


def test_unknown_acronyms_become_candidates():
    detection = detect_terms("Revisa el ETL y el B2B, OK?", GLOSSARY)
    assert detection.new_candidates == ["ETL", "B2B"]
    assert [(term.term, term.known) for term in detection.terms] == \
        [("ETL", False), ("B2B", False)]


def test_known_acronyms_are_not_candidates():
    assert detect_terms("La API", GLOSSARY).new_candidates == []


def test_existing_candidate_is_detected_but_not_proposed_again():
    glossary = GLOSSARY + [GlossaryEntry(term="ETL")]
    detection = detect_terms("el ETL", glossary)
    assert detection.new_candidates == []
    assert [(term.term, term.known) for term in detection.terms] == [("ETL", False)]


def test_rejected_terms_are_ignored_and_not_proposed_again():
    glossary = [entry("SEO", Ambito.MARKETING, estado=Estado.RECHAZADO)]
    detection = detect_terms("mejorar el SEO", glossary)
    assert detection.terms == []
    assert detection.new_candidates == []
