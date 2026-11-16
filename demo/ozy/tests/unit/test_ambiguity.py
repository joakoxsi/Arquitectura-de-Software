from app.detector import detect_terms
from app.domain import AudienceLevel, Estado
from app.seed import seed_glossary
from app.translator import render_explanation


def detect(repos, content):
    return detect_terms(content, repos.glossary.find_all()).terms


def test_pr_has_three_meanings_and_is_ambiguous(repos):
    seed_glossary(repos.glossary)
    [pr] = detect(repos, "Aprueben el PR")
    assert pr.ambiguous
    assert sorted(entry.ambito.value for entry in pr.meanings) == \
        ["finanzas", "marketing", "software"]


def test_single_meaning_is_not_ambiguous(repos):
    seed_glossary(repos.glossary)
    [kpi] = detect(repos, "Subió el KPI")
    assert kpi.known and not kpi.ambiguous


def test_rejected_definitions_do_not_count_for_ambiguity(repos):
    seed_glossary(repos.glossary)
    entries = {entry.ambito.value: entry for entry in repos.glossary.find_by_term("PR")}
    repos.glossary.set_estado(entries["marketing"].id, Estado.RECHAZADO, "u1")
    assert detect(repos, "el PR")[0].ambiguous
    repos.glossary.set_estado(entries["finanzas"].id, Estado.RECHAZADO, "u1")
    [pr] = detect(repos, "el PR")
    assert not pr.ambiguous
    assert [entry.ambito.value for entry in pr.meanings] == ["software"]


def test_explanation_lists_every_meaning_of_an_ambiguous_term(repos):
    seed_glossary(repos.glossary)
    text = render_explanation(detect(repos, "el PR"), AudienceLevel.BASICO)
    assert "significa cosas distintas" in text
    for meaning in ("Pull Request", "Public Relations", "Purchase Request"):
        assert meaning in text
    assert "ambiguo" in render_explanation(detect(repos, "el PR"), AudienceLevel.EXPERTO)
