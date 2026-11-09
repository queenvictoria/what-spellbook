"""HTTP API: routing, serialisation and - most importantly - error mapping.

Every endpoint is exercised through the real app with a fake index and a fake model, so
routing, validation and status codes are all real. A wrong status code is a contract bug
the front end will hit, and it cannot be caught by testing the service directly.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.libs import cache, characters, llm, rules

from conftest import BOOKS_ANSWER, FakeDB, FakeLLM

LOIS = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Current Level": 5,
    "Party": "Barbarian, Fighter, Druid",
    "Passive Scores": "Perception 12, Insight 15, Investigation 13",
    "Armor Class": 14,
    "Spell Save DC": 15,
    "Spell Attack Bonus": "+7",
}

SCENARIO = "A rust monster eats the fighter's plate armour mid-fight."


class FakeServiceLLM(FakeLLM):
    """A backend whose response can be swapped, and which can be made to fail."""

    def __init__(self, response=BOOKS_ANSWER):
        super().__init__()
        self.response = response

    def invoke(self, prompt):
        return self.response


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A client wired to fakes, with the character name overridden.

    The sheet is read lazily on the first request, so a test may edit ``client.sheet``
    before asking anything and the service will see the edited version.
    """
    fake_llm = FakeServiceLLM()
    app = create_app(vector_db=FakeDB(), backend=fake_llm, character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: client.sheet)
    client = TestClient(app)
    client.sheet = dict(LOIS)
    return client


# --- meta ---


def test_health_reports_the_session(api):
    body = api.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["character"] == "Lois"
    assert body["index_version"] >= 3


def test_openapi_schema_is_valid(api):
    """The front end generates its client from this, so it must serialise."""
    schema = api.get("/openapi.json").json()
    assert "/api/scenario" in schema["paths"]
    assert schema["info"]["title"] == "what-spellbook API"


def test_sheet_keys_are_listed(api):
    """A client uses this to offer completions, so it must name what lookup accepts."""
    keys = api.get("/api/sheet-keys").json()
    assert "passive perception" in keys
    assert "ac" in keys
    assert keys == sorted(keys)


# --- character ---


def test_character_returns_the_sheet(api):
    body = api.get("/api/character").json()
    assert body["name"] == "Lois"
    assert body["sheet"]["Class"] == "Warlock"
    assert "Class: Warlock" in body["text"]


def test_character_lookup_is_exact_and_does_not_call_the_model(api):
    """A sheet fact must not be routed to the model: it is instant and already known."""
    body = api.get("/api/character/ask", params={"question": "passive perception"}).json()
    assert body["answer"] == "12"
    assert body["source"] == "sheet"


def test_character_lookup_reports_its_sheet_field(api):
    """Without the field name the number is unverifiable, so a client must receive it."""
    body = api.get("/api/character/ask", params={"question": "ac"}).json()
    assert body["answer"] == "14"
    assert body["field_name"] == "Armor Class"


def test_character_duplicate_spell_is_answered_from_the_sheet(api):
    sheet = dict(LOIS, **{
        "Always Prepared Spells": "Light, Sacred Flame",
        "Cantrips From Other Sources": "Light, Mending",
    })
    api.sheet = sheet
    body = api.get("/api/character/ask",
                   params={"question": "why do I have two Light spells"}).json()
    assert body["source"] == "sheet"
    assert "2 separate sources" in body["answer"]


def test_character_question_without_a_question_is_rejected(api):
    assert api.get("/api/character/ask", params={"question": ""}).status_code == 422


# --- generation ---


def test_scenario_returns_books(api):
    response = api.post("/api/scenario", json={"scenario": SCENARIO})
    assert response.status_code == 200
    body = response.json()
    assert len(body["books"]) == 2
    assert body["books"][0]["name"] == "Ambush and Control"
    assert body["from_cache"] is False


def test_scenario_reports_per_phase_timings(api):
    body = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    assert set(body["timings"]["phases"]) == {"retrieval", "prompt", "books"}
    assert body["timings"]["total_seconds"] >= 0


def test_scenario_reports_legality_warnings(api):
    """A book whose picks are illegal must not be returned as if it were usable."""
    assert isinstance(api.post("/api/scenario", json={"scenario": SCENARIO}).json()["warnings"], list)


def test_a_repeat_scenario_is_served_from_the_cache(api):
    first = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    second = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]


def test_cached_returns_null_before_generating(api):
    assert api.get("/api/cached", params={"scenario": "never run"}).json() is None


def test_cached_returns_the_run_after_generating(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    body = api.get("/api/cached", params={"scenario": SCENARIO}).json()
    assert body["from_cache"] is True
    assert len(body["books"]) == 2


def test_empty_scenario_is_rejected(api):
    assert api.post("/api/scenario", json={"scenario": ""}).status_code == 422


def test_missing_scenario_field_is_rejected(api):
    assert api.post("/api/scenario", json={}).status_code == 422


def test_scenario_reports_an_empty_completion_as_502(api, monkeypatch):
    """A model that returns nothing is the server's problem, not a bad request."""
    monkeypatch.setattr(
        "backend.libs.llm.invoke",
        lambda *a, **k: (_ for _ in ()).throw(llm.EmptyCompletion("no output")),
    )
    response = api.post("/api/scenario", json={"scenario": "a fresh scenario"})
    assert response.status_code == 502


def test_scenario_reports_an_unreachable_model_as_503(api, monkeypatch):
    monkeypatch.setattr(
        "backend.libs.llm.invoke",
        lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("connection refused")),
    )
    response = api.post("/api/scenario", json={"scenario": "another scenario"})
    assert response.status_code == 503


def test_an_unreachable_model_says_how_to_fix_it(api, monkeypatch):
    """The detail is the whole point of the 503: it is what the UI shows the user.

    A bare "connection refused" tells someone the model is down but not that the fix is one
    command, so the message is asserted rather than only the status.
    """
    monkeypatch.setattr(
        "backend.libs.llm.invoke",
        lambda *a, **k: (_ for _ in ()).throw(
            llm.LLMUnavailable(
                llm.explain_failure(ConnectionError("Failed to connect to Ollama."),
                                    model="qwen3.5:4b")
            )
        ),
    )
    response = api.post("/api/scenario", json={"scenario": "a third scenario"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "ollama serve" in detail
    assert "qwen3.5:4b" in detail


def test_a_dead_embedding_server_is_503_not_500(api, monkeypatch):
    """Embeddings go to the same Ollama, so the same failure arrives by another stack.

    It reaches the route from ``retrieval`` rather than from ``invoke``, and an untyped
    ``ConnectionError`` there would surface as an unhandled 500 - which tells the caller to
    retry a request that cannot work until someone starts the server.
    """
    monkeypatch.setattr(
        "backend.libs.retrieval.retrieve",
        lambda *a, **k: (_ for _ in ()).throw(
            llm.EmbeddingUnavailable("Ollama is not reachable at http://127.0.0.1:11434")
        ),
    )
    response = api.post("/api/scenario", json={"scenario": "a fourth scenario"})
    assert response.status_code == 503
    assert "not reachable" in response.json()["detail"]


def test_an_embedding_failure_is_a_model_failure_too(api, monkeypatch):
    """``EmbeddingUnavailable`` subclasses ``LLMUnavailable``, so no route needs to name it.

    That is the reason for the subclass: five routes already handle the model being down, and
    a sibling type would have had to be added to each of them or fall through as a 500.
    """
    assert issubclass(llm.EmbeddingUnavailable, llm.LLMUnavailable)


def test_ask_without_cached_books_is_404(api):
    response = api.post("/api/ask", params={"scenario": "never run"},
                        json={"question": "why?"})
    assert response.status_code == 404


def test_ask_refines_a_cached_scenario(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    response = api.post("/api/ask", params={"scenario": SCENARIO},
                        json={"question": "What about fire resistance?"})
    assert response.status_code == 200


# --- history and runs ---


def test_history_is_empty_before_generating(api):
    assert api.get("/api/history").json() == []


def test_history_lists_the_run_not_the_books(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    history = api.get("/api/history").json()
    assert len(history) == 1
    assert history[0]["scenario"] == SCENARIO
    assert history[0]["book_count"] == 2
    assert history[0]["book_names"] == ["Ambush and Control", "Denial and Escape"]


def test_history_includes_the_timings(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    assert api.get("/api/history").json()[0]["timings"]["total_seconds"] >= 0


def test_history_identifies_a_run_without_exposing_a_filesystem_path(api):
    """A browser cannot use a server path, and handing out one leaks the layout."""
    api.post("/api/scenario", json={"scenario": SCENARIO})
    run = api.get("/api/history").json()[0]
    assert run["id"]
    assert "/" not in run["id"]
    assert "directory" not in run


def test_run_can_be_reopened_for_reading(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    run = api.get("/api/history").json()[0]["id"]
    body = api.get(f"/api/runs/{run}").json()
    assert body["scenario"] == SCENARIO
    assert len(body["books"]) == 2


def test_run_can_be_reopened_by_scenario_fragment(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    body = api.get("/api/runs/rust monster").json()
    assert body["scenario"] == SCENARIO


def test_unknown_run_is_404(api):
    assert api.get("/api/runs/no-such-run").status_code == 404


def _run_id(client) -> str:
    return client.get("/api/history").json()[0]["id"]


def test_rating_a_run_records_the_score(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    rated = api.post(f"/api/runs/{_run_id(api)}/rate", json={"score": 5}).json()
    assert len(rated) == 2
    assert all(book["rating"]["score"] == 5 for book in rated)


def test_rating_one_book_leaves_its_sibling_alone(api):
    """A rating belongs to one book; rating one must not silently rate the other."""
    api.post("/api/scenario", json={"scenario": SCENARIO})
    run = _run_id(api)
    rated = api.post(f"/api/runs/{run}/rate", json={"score": 4, "book": "ambush"}).json()
    assert len(rated) == 1

    reopened = api.get(f"/api/runs/{run}").json()["books"]
    scores = {book["name"]: (book["rating"] or {}).get("score") for book in reopened}
    assert scores["Ambush and Control"] == 4
    assert scores["Denial and Escape"] is None


def test_rating_accepts_a_numeric_book_index(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    rated = api.post(f"/api/runs/{_run_id(api)}/rate", json={"score": 3, "book": "2"}).json()
    assert len(rated) == 1
    assert rated[0]["index"] == 2


def test_rating_records_notes_and_outcome(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    rated = api.post(f"/api/runs/{_run_id(api)}/rate",
                     json={"score": 5, "notes": "won the fight", "outcome": "won"}).json()
    assert rated[0]["rating"]["notes"] == "won the fight"
    assert rated[0]["rating"]["outcome"] == "won"


@pytest.mark.parametrize("score", [0, 6, -1, 99])
def test_rating_score_is_range_checked(api, score):
    """The CLI only accepts 1-5; the API must not accept what the CLI rejects."""
    response = api.post("/api/runs/anything/rate", json={"score": score})
    assert response.status_code == 422


def test_rating_an_unknown_book_is_404(api):
    """The error must list the real book names, or the caller cannot correct itself."""
    api.post("/api/scenario", json={"scenario": SCENARIO})
    response = api.post(f"/api/runs/{_run_id(api)}/rate", json={"score": 5, "book": "wrong publication"})
    assert response.status_code == 404


def test_a_generated_run_reports_its_id(api):
    """The front end rates by id, so a generation has to carry one.

    Rating by scenario text is ambiguous: a run is keyed on the scenario *and* the
    character, level and book count, so two runs can share a scenario and the wrong one
    gets rated. The id is the only unambiguous handle.
    """
    body = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    assert body["run_id"] == _run_id(api)


def test_a_replayed_run_reports_its_id(api):
    """A run reopened from history must be rateable too, so replay carries the id."""
    api.post("/api/scenario", json={"scenario": SCENARIO})
    run = _run_id(api)
    assert api.get(f"/api/runs/{run}").json()["run_id"] == run


def test_a_run_id_rates_the_run_it_names(api):
    """The id from the generation is the one the rate endpoint accepts."""
    body = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    rated = api.post(f"/api/runs/{body['run_id']}/rate",
                     json={"score": 4, "book": "1"}).json()
    assert len(rated) == 1
    assert rated[0]["rating"]["score"] == 4


def test_a_run_id_is_not_the_scenario_text(api):
    """The id must be opaque, or a client could pass the scenario and double-encode it.

    This is the bug this contract exists to prevent: the front end encoded the scenario
    text and the client encoded it again, so the request went to a run named
    "Three%2520kobolds..." and 404'd.
    """
    body = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    assert body["run_id"] != SCENARIO
    assert "%" not in body["run_id"]


# --- rules ---


def test_rules_answers_are_grounded_and_cached(api, monkeypatch):
    """The second ask must be answered from the stored answer, not asked again.

    Deliberately *not* stubbing retrieval. The whole point of this test is the cache, and
    the cache is downstream of retrieval, so a stub that fakes the retrieved text also
    fakes the thing under test - and worse, a stub corpus changes the term-frequency model
    the matcher ranks headings with, which is how an earlier version of this test started
    asserting a 404. Only the model call is stubbed.
    """
    calls = []

    def fake_invoke(*args, **kwargs):
        calls.append(args)
        return "Walls, trees and other obstacles provide cover."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    first = api.get("/api/rules", params={"question": "how does cover work"}).json()
    assert first["source"] == "rules"
    assert first["from_cache"] is False
    # Either the glossary's one-line "Cover" or the chapter's longer one, whichever the
    # matcher prefers - both are the rule. What the citation must be is a *file in the
    # vendored SRD*, not a URL: the source is local now, and a URL here would look
    # clickable and lead nowhere.
    assert len(first["citations"]) == 1
    assert first["citations"][0].startswith("context/srd/")
    assert first["citations"][0].split("#")[0].endswith(".md")
    assert len(calls) == 1

    second = api.get("/api/rules", params={"question": "how does cover work"}).json()
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]
    assert len(calls) == 1, "the second ask must not have reached the model"


def test_a_question_no_heading_names_is_answered_as_interpreted(api, monkeypatch):
    """The fallback must reach the model, and must say it was an interpretation.

    "what is a spell attack" is answered by the glossary's own "Spell Attack" heading, but
    the precise path refuses it because the question's most distinctive term is the generic
    "attack". Retrieval is real here for the same reason as the test above: the point is
    which path ran, and stubbing retrieval would decide that in the stub.
    """
    prompts = []

    def fake_invoke(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        return "Roll a d20 and add your spell attack bonus."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    body = api.get("/api/rules", params={"question": "what is a spell attack"}).json()
    assert body["source"] == "rules-inferred"
    assert body["citations"][0].startswith("context/srd/")
    # The interpreted prompt is a different prompt, not the quoting one: it has to permit
    # connecting the retrieved text to the question, which the quoting prompt forbids.
    assert "not necessarily" in prompts[0]

    # And the label survives the cache, which is the only place it can come from on a hit.
    again = api.get("/api/rules", params={"question": "what is a spell attack"}).json()
    assert again["from_cache"] is True
    assert again["source"] == "rules-inferred"
    assert len(prompts) == 1, "the second ask must not have reached the model"


def test_contextual_explains_a_fragment_selected_from_prose(api, monkeypatch):
    """The contextual menu's whole path, from the query parameter to the badge.

    The parameter is spelled ``selected_text`` because FastAPI names it, and the front end
    spent its entire life sending ``selectedText`` - every request 422'd, so the feature was
    never once exercised end to end. Retrieval is real here so that the path the selection
    takes is the thing under test: "2 beams" is refused by both anchored paths and is only
    answered by the selection path, so stubbing retrieval would decide the outcome in the
    stub.
    """
    prompts = []

    def fake_invoke(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        return "At level 5 Eldritch Blast creates two beams."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    response = api.get("/api/rules/contextual", params={"selected_text": "2 beams"})
    assert response.status_code == 200
    body = response.json()
    # A fragment is never quoted, so the badge must not claim it is.
    assert body["source"] == "rules-inferred"
    assert body["question"] == "2 beams"
    assert body["citations"][0].startswith("context/srd/")
    assert "Eldritch Blast" in prompts[0]

    # The surrounding sentence reaches the prompt, which is what lets the model read
    # "2 beams" as the Eldritch Blast beams rather than two beams of anything.
    with_context = api.get("/api/rules/contextual", params={
        "selected_text": "the beams at level 5",
        "context": "Eldritch Blast creates two beams at level 5.",
    })
    assert with_context.status_code == 200
    assert "WHERE THE SELECTED TEXT APPEARS" in prompts[1]
    assert "Eldritch Blast creates two beams" in prompts[1]


def test_contextual_rejects_a_selection_rooted_in_no_srd_vocabulary(api, monkeypatch):
    """The vocabulary gate, reached through the API rather than through the service.

    "Rust Metal" is a monster ability the 2024 SRD does not carry, so there is no rule to
    quote and a 404 is the honest report. Answering it from nearby prose would read as
    sourced.
    """

    def fail_invoke(*args, **kwargs):
        raise AssertionError("the model must not be called for an unanswerable selection")

    monkeypatch.setattr("backend.libs.llm.invoke", fail_invoke)
    response = api.get("/api/rules/contextual", params={"selected_text": "Rust Metal"})
    assert response.status_code == 404
    assert "Rust Metal" in response.json()["detail"]


def test_contextual_requires_a_selection(api):
    """An empty selection is the caller's request being wrong, not a rules gap."""
    assert api.get("/api/rules/contextual", params={"selected_text": ""}).status_code == 422
    assert api.get("/api/rules/contextual").status_code == 422


def test_a_contextual_answer_is_cached_under_the_selection(api, monkeypatch):
    """Re-asking costs nothing, and the *interpretation* label survives the cache.

    The label is recomputed nowhere on a hit - retrieval does not run - so it has to have
    been stored. Serving an interpretation as a quotation is the failure the label exists
    to prevent.
    """
    calls = []

    def fake_invoke(*args, **kwargs):
        calls.append(args)
        return "Two beams means two separate attack rolls."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    first = api.get("/api/rules/contextual", params={"selected_text": "2 beams"}).json()
    assert first["from_cache"] is False
    assert first["source"] == "rules-inferred"

    second = api.get("/api/rules/contextual", params={"selected_text": "2 beams"}).json()
    assert second["from_cache"] is True
    assert second["source"] == "rules-inferred"
    assert second["answer"] == first["answer"]
    assert len(calls) == 1, "the second ask must not have reached the model"


def test_rules_reports_a_missing_rule_as_404(api, monkeypatch):
    """A question the SRD does not discuss at all is the caller's request being wrong.

    All three retrieval paths must fail for this to be a 404: the precise path refuses a
    question no heading names, the inferred path refuses one whose subject the SRD never
    mentions, and the index lane refuses one whose embedding finds no SRD section. Stubbing
    only ``gather`` would let a real path answer from the live corpus, and the test would
    pass while proving nothing.
    """

    def fake_gather(question, *args, **kwargs):
        raise rules.RulesUnavailable("the SRD does not define a Short Rest")

    monkeypatch.setattr(rules, "gather", fake_gather)
    monkeypatch.setattr(rules, "gather_inferred", fake_gather)
    monkeypatch.setattr(rules, "gather_from_index", fake_gather)
    response = api.get("/api/rules", params={"question": "what is a short rest"})
    assert response.status_code == 404
    assert "Short Rest" in response.json()["detail"]


def test_character_missing_is_404(tmp_path, monkeypatch):
    """A sheet on disk may be renamed or deleted while the server runs, so this is
    possible at any time - and it is the caller's reference that is wrong, not us."""

    def missing(name, **kwargs):
        raise characters.CharacterNotFound(f"No character sheet called '{name}'.")

    monkeypatch.setattr(characters, "load_character_data", missing)
    app = create_app(vector_db=FakeDB(), backend=FakeServiceLLM(),
                     character_name="ghost", cache_dir=str(tmp_path / "cache"))
    response = TestClient(app).get("/api/character")
    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]


def test_health_still_answers_when_no_character_loads(tmp_path, monkeypatch):
    """Liveness must not depend on a character: a client polls this to know we are up."""
    monkeypatch.setattr(characters, "load_character_data",
                        lambda name, **kw: (_ for _ in ()).throw(
                            characters.CharacterNotFound("none")))
    app = create_app(vector_db=FakeDB(), backend=FakeServiceLLM(),
                     character_name="ghost", cache_dir=str(tmp_path / "cache"))
    body = TestClient(app).get("/api/health").json()
    assert body["status"] == "ok"
    assert body["character"] is None


def test_spell_returns_the_vendored_text_verbatim(api):
    """Deterministic, so it cannot hallucinate: no model sits between SRD and caller."""
    response = api.get("/api/spell", params={"name": "Fireball"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Fireball"
    assert "8d6 Fire damage" in body["text"]
    # Anchored to the spell's own heading, so the path is a link to the rule rather than to
    # 325KB of spell descriptions.
    assert body["url"] == "context/srd/spells.md#fireball"
    assert body["source"] == "vendored-srd-5.2.1"


def test_a_spell_in_neither_source_is_a_404_with_the_reason(api):
    """A 404 now means a genuine miss, not a branding difference.

    The corpus is searched after the SRD, so "Tenser's Floating Disk" resolves from the
    corpus. Only a name in neither source reaches this branch, and the message has to say
    so rather than implying the SRD is the only place a spell could be.
    """
    response = api.get("/api/spell", params={"name": "Flaming Death Ray"})
    assert response.status_code == 404
    assert "Flaming Death Ray" in response.json()["detail"]


def test_a_corpus_only_spell_is_served_from_the_corpus(api):
    """Thorn Whip is absent from the SRD but is a cantrip this app recommends.

    Answering 404 for it would make every spell link in the books useless, so the corpus
    fills the gap and the response says which source it came from.
    """
    response = api.get("/api/spell", params={"name": "Thorn Whip"})
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "retrieval-corpus"
    assert "1d6 Piercing damage" in body["text"]


def test_an_srd_spell_prefers_the_srd(api):
    """The SRD is the 2024 authority, so it wins when both sources have the spell."""
    body = api.get("/api/spell", params={"name": "Fireball"}).json()
    assert body["source"] == "vendored-srd-5.2.1"
    assert body["url"] == "context/srd/spells.md#fireball"


def test_spell_requires_a_name(api):
    assert api.get("/api/spell", params={"name": ""}).status_code == 422


def test_a_spell_is_contextualised_to_the_loaded_character(api):
    """The card shows what the spell does at *this* character's level.

    Lois is a level 5 Warlock, so Eldritch Blast has two beams - and the note is read out
    of the spell's own text, so it is a rule rather than a model's recollection of one.
    """
    body = api.get("/api/spell", params={"name": "Eldritch Blast"}).json()
    assert body["scaling"] == "2 beams (L5)"


def test_the_note_follows_the_character_level(api):
    """The same spell, a different sheet: the note is about the character, not the spell."""
    api.sheet = {**LOIS, "Current Level": 11}
    body = api.get("/api/spell", params={"name": "Eldritch Blast"}).json()
    assert body["scaling"] == "3 beams (L11)"


def test_a_spell_that_does_not_scale_has_no_note(api):
    """Null rather than an empty string, so the card can tell "nothing" from "unknown"."""
    body = api.get("/api/spell", params={"name": "Fireball"}).json()
    assert body["scaling"] is None


def test_a_cantrip_below_its_first_upgrade_has_no_note(api):
    """A level 3 Warlock's Eldritch Blast has one beam, and the level 5 row would be wrong."""
    api.sheet = {**LOIS, "Current Level": 3}
    body = api.get("/api/spell", params={"name": "Eldritch Blast"}).json()
    assert body["scaling"] is None


def test_an_invocation_has_no_note(api):
    """An invocation's effect is not a value that changes with level."""
    body = api.get("/api/invocation", params={"name": "Agonizing Blast"}).json()
    assert body["scaling"] is None


def test_the_note_is_absent_without_a_character(api):
    """No sheet means no level, and a guessed level is worse than no note."""
    api.sheet = {k: v for k, v in LOIS.items() if k != "Current Level"}
    body = api.get("/api/spell", params={"name": "Eldritch Blast"}).json()
    assert body["scaling"] is None


def test_a_missing_sheet_does_not_break_the_spell_lookup(api, monkeypatch):
    """The note is an addition to a card whose text comes from a file.

    A sheet that cannot be read must not turn a working spell lookup into a 404 - the spell
    is still quotable, it just cannot be contextualised.
    """
    def missing(name, **kwargs):
        raise characters.CharacterNotFound(f"No character sheet at '{name}.yaml'.")

    monkeypatch.setattr("backend.libs.characters.load_character_data", missing)
    response = api.get("/api/spell", params={"name": "Eldritch Blast"})
    assert response.status_code == 200
    assert response.json()["scaling"] is None
    assert "crackling energy" in response.json()["text"]


def test_a_contextualised_note_is_cached_across_requests(api, monkeypatch):
    """A drawer opened twice must not pay for the same phrase twice.

    Booming Blade is the one corpus cantrip whose scaling the reader cannot parse, so it is
    the only spell that reaches the model - which makes it the only one a cache can help.
    """
    calls = []

    def counting(_backend, prompt):
        calls.append(prompt)
        return "extra 1d8 thunder damage on hit"

    monkeypatch.setattr("backend.libs.llm.invoke", counting)
    first = api.get("/api/spell", params={"name": "Booming Blade"}).json()
    second = api.get("/api/spell", params={"name": "Booming Blade"}).json()
    assert first["scaling"] == second["scaling"] == "extra 1d8 thunder damage on hit (L5)"
    assert len(calls) == 1


def test_invocation_is_served_from_the_vendored_srd(api):
    """An invocation is not a spell, but the SRD does carry it - in the class chapter.

    The response shape matches a spell's because the same card renders both, and the
    source says the text is the SRD's rather than our own class context's.
    """
    response = api.get("/api/invocation", params={"name": "Agonizing Blast"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Agonizing Blast"
    assert body["source"] == "vendored-srd-5.2.1"
    assert body["url"] == "context/srd/classes.md#agonizing-blast"
    assert "Charisma modifier" in body["text"]


def test_an_unknown_invocation_is_a_404(api):
    response = api.get("/api/invocation", params={"name": "Flaming Death Ray"})
    assert response.status_code == 404
    assert "Flaming Death Ray" in response.json()["detail"]


def test_the_link_list_covers_spells_and_invocations(api):
    """One list, because the prose names both in the same sentence.

    The books write "Agonizing Blast on Eldritch Blast" - a spell and an invocation in one
    clause - so a list holding only spells leaves half of that sentence as dead text.
    """
    names = api.get("/api/spells").json()
    assert "Fireball" in names
    assert "Thorn Whip" in names
    assert "Hideous Laughter" in names
    assert "Agonizing Blast" in names
    assert "Repelling Blast" in names
    assert "Eldritch Spear" in names
    assert "Mask of Many Faces" in names
    assert "Pact of the Tome" in names


def test_every_name_in_the_link_list_resolves(api):
    """A name offered for linking must not 404, whichever endpoint answers it.

    The front end tries `/api/spell` and falls back to `/api/invocation`, so a name is
    only linkable if one of the two has it. Checked across the whole list rather than a
    sample, because one bad name is invisible in a spot check.
    """
    names = api.get("/api/spells").json()
    misses = []
    for name in names:
        if api.get("/api/spell", params={"name": name}).status_code == 200:
            continue
        if api.get("/api/invocation", params={"name": name}).status_code == 200:
            continue
        misses.append(name)
    assert misses == [], f"{len(misses)} linkable names do not resolve: {misses[:5]}"


def test_contextual_attaches_the_documents_it_is_given(api, monkeypatch):
    """The attached documents must reach the prompt, and the response must report them.

    A book's sentence names the spells it is about, and no retrieval over the *selection* can
    turn those names into their rules - a spell's description is written in different words
    from a sentence about it. Attaching them is the difference between an answer and "the SRD
    does not cover this".
    """
    prompts = []

    def fake_invoke(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        return "Thorn Whip is a 30-foot melee spell attack for 1d6 piercing."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    selection = ("If Repelling Blast misses, Thorn Whip is a 30-ft melee spell attack "
                 "for 2d6")
    body = api.get("/api/rules/contextual", params={
        "selected_text": selection,
        "document": ["Thorn Whip", "Repelling Blast"],
    }).json()

    # The spell's own text is in the prompt, not just its name.
    assert "MELEE SPELL ATTACK" in prompts[0].upper()
    assert "1d6" in prompts[0]
    assert body["attachments"] == ["Thorn Whip", "Repelling Blast"]


def test_contextual_resolves_names_from_the_selection_when_none_are_given(api, monkeypatch):
    """A caller that sends only the selection still gets the documents.

    The UI resolves the mentions itself so the attached list matches the links the reader was
    shown, but the endpoint must not depend on that - a selection is enough on its own.
    """
    prompts = []

    def fake_invoke(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        return "Answer."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    body = api.get("/api/rules/contextual", params={
        "selected_text": "Thorn Whip is a 30-ft melee spell attack",
    }).json()

    assert body["attachments"] == ["Thorn Whip"]
    assert "1d6" in prompts[0]


def test_an_attached_document_rescues_a_selection_the_srd_cannot_answer(api, monkeypatch):
    """A sentence built of vocabulary the SRD lacks is answerable when its documents are
    attached.

    Without them the selection path refuses, correctly: "Rust Metal" is not in the 2024 SRD
    and nearby prose would read as sourced. But a *question about a spell* does not need an
    SRD rule behind the sentence - the spell's own description is the rule.
    """

    def fake_invoke(*args, **kwargs):
        return "Answered from the attached spell."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)

    selection = "Rust Metal corrodes the plate armour"
    # Unanswerable with nothing attached...
    assert api.get("/api/rules/contextual",
                   params={"selected_text": selection}).status_code == 404
    # ...and answerable once a document is, because that document is the rule.
    rescued = api.get("/api/rules/contextual", params={
        "selected_text": selection, "document": "Mending"})
    assert rescued.status_code == 200
    assert rescued.json()["attachments"] == ["Mending"]


def test_contextual_reports_the_documents_a_cached_answer_used(api, monkeypatch):
    """A cache hit skips retrieval *and* resolution, so the names have to be stored.

    "What the model actually read" is part of the answer: reporting the SRD does not cover a
    spell reads differently once it is clear the spell was never attached.
    """
    calls = []

    def fake_invoke(*args, **kwargs):
        calls.append(args)
        return "Answer."

    monkeypatch.setattr("backend.libs.llm.invoke", fake_invoke)
    params = {"selected_text": "Thorn Whip is a melee spell attack", "document": "Thorn Whip"}

    first = api.get("/api/rules/contextual", params=params).json()
    assert first["attachments"] == ["Thorn Whip"]

    second = api.get("/api/rules/contextual", params=params).json()
    assert second["from_cache"] is True
    assert second["attachments"] == ["Thorn Whip"]
    assert len(calls) == 1


def test_scenario_returns_the_preamble_and_pairings(api):
    """Both are separate fields, so a client never has to parse them out of a book."""
    body = api.post("/api/scenario", json={"scenario": SCENARIO}).json()
    assert "preamble" in body and "pairings" in body


def test_a_reopened_run_carries_the_preamble_and_pairings(api):
    """A run read from history must render exactly as it did when generated."""
    api.post("/api/scenario", json={"scenario": SCENARIO})
    run = api.get("/api/history").json()[0]["id"]
    body = api.get(f"/api/runs/{run}").json()
    assert "preamble" in body and "pairings" in body


# --- index search ---


def test_search_returns_distinct_spells_with_their_metadata(api):
    """The diagnostic surface: what is in the index, not what is legal for a character."""
    body = api.get("/api/search", params={"query": "fire", "mode": "vector"}).json()
    assert body["mode"] == "vector"
    assert body["hits"], "the fake catalogue has spells to find"
    hit = body["hits"][0]
    assert hit["name"] and hit["level_label"]
    assert isinstance(hit["classes"], list)


def test_search_text_mode_browses_with_no_query(api):
    """An empty query lists what the filters admit, which is how a filter gets checked."""
    body = api.get("/api/search", params={"query": "", "mode": "text"}).json()
    assert body["total_matching"] >= 1
    assert body["hits"]


def test_search_echoes_the_filter_clause_it_sent(api):
    """A filter that silently matches nothing is the commonest failure here.

    The clause is the fastest way to see why, so it is part of the response rather than
    something a caller has to reconstruct.
    """
    body = api.get("/api/search", params={"query": "", "mode": "text",
                                          "class": ["Wizard"]}).json()
    assert body["where"] == {"$and": [{"doc_type": "spell"}, {"classes": "Wizard"}]}
    assert body["filters"]["classes"] == ["Wizard"]


def test_search_reports_a_class_the_index_never_uses(api):
    """A filter must never widen the search, and the caller is told why it matched nothing."""
    body = api.get("/api/search", params={"query": "fire", "mode": "vector",
                                          "class": ["Artificer"]}).json()
    assert body["hits"] == []
    assert "lists that class" in body["note"]


def test_search_rejects_a_mode_it_does_not_have(api):
    """400, not 500: the request cannot work and retrying it will not help."""
    response = api.get("/api/search", params={"query": "fire", "mode": "fuzzy"})
    assert response.status_code == 400
    assert "Unknown search mode" in response.json()["detail"]


def test_search_rejects_a_vector_query_with_nothing_to_embed(api):
    response = api.get("/api/search", params={"query": "", "mode": "vector"})
    assert response.status_code == 400
    assert "needs some text" in response.json()["detail"]


def test_search_rejects_an_inverted_level_range(api):
    response = api.get("/api/search", params={"query": "fire", "mode": "text",
                                              "level_min": 5, "level_max": 2})
    assert response.status_code == 400


def test_search_facets_describe_the_index(api):
    """Filter values come from the index, so a class that exists nowhere is never offered."""
    body = api.get("/api/search/facets").json()
    assert body["index_version"] >= 4
    assert body["facets"]["spells"] >= 1
    assert body["facets"]["chunks"] >= body["facets"]["spells"]
    assert any(level["label"] == "Cantrip" for level in body["facets"]["levels"])
    assert any(facet["value"] == "srd" for facet in body["facets"]["doc_types"])


# --- browsing the vendored SRD ---


def test_srd_lists_every_vendored_file_with_its_headings(api):
    """The table of contents, so the Rules screen can draw a tree without the text.

    ``PROVENANCE.md`` must not appear: it is the CC-BY-4.0 attribution, not SRD text, and
    offering it as a rule would let licence boilerplate answer a question about "rights".
    """
    response = api.get("/api/srd")
    assert response.status_code == 200
    documents = response.json()
    names = [document["name"] for document in documents]
    assert "classes" in names and "equipment" in names and "spells" in names
    assert "PROVENANCE" not in names

    classes = next(document for document in documents if document["name"] == "classes")
    assert classes["title"] == "Classes"
    assert classes["path"] == "context/srd/classes.md"
    # Nested, not flat: the whole point of the tree is that a subclass sits under its class.
    assert classes["headings"][0]["text"] == "Classes"
    assert any(child["text"] == "Barbarian" for child in classes["headings"][0]["children"])


def test_srd_slugs_are_unique_within_a_document(api):
    """The SRD repeats headings, so a slug from the text alone would collide.

    ``classes.md`` has six ``Level 1: Spellcasting`` sections, one per class. Without
    de-duplication every link after the first would open the wrong class's feature.
    """
    documents = api.get("/api/srd").json()

    def slugs(headings):
        for heading in headings:
            yield heading["slug"]
            yield from slugs(heading["children"])

    for document in documents:
        found = list(slugs(document["headings"]))
        assert len(found) == len(set(found)), document["name"]


def test_srd_section_returns_the_rule_verbatim(api):
    """Deterministic, like a spell: no model sits between the file and the caller."""
    response = api.get("/api/srd/equipment", params={"slug": "coins"})
    assert response.status_code == 200
    body = response.json()
    assert body["heading"] == "Coins"
    assert body["title"] == "Equipment"
    assert body["path"] == "context/srd/equipment.md"
    assert body["source"] == "vendored-srd-5.2.1"
    assert "Copper Piece (CP)" in body["text"]


def test_srd_section_converts_tables_to_markdown(api):
    """The numbers in a table *are* the rule, so a table must survive the conversion.

    ``### Cover``'s prose only says "as detailed in the Cover table" - a renderer that
    dropped the table would show a confident rule with its bonuses missing.
    """
    body = api.get("/api/srd/playing-the-game", params={"slug": "cover"}).json()
    assert "| Degree | Benefit to Target |" in body["text"]
    assert "+2 bonus to AC" in body["text"]
    assert "<table>" not in body["text"]


def test_srd_section_stops_at_the_next_heading_of_the_same_level(api):
    """A section is its own text, not the rest of the file."""
    body = api.get("/api/srd/equipment", params={"slug": "coins"}).json()
    assert "Weapons" not in body["text"]


def test_srd_whole_document_needs_no_slug(api):
    """A click on the file name asks for the file, not for a section of it."""
    body = api.get("/api/srd/equipment").json()
    assert body["heading"] == "Equipment"
    assert body["slug"] == ""
    assert "## Coins" in body["text"]
    assert "## Weapons" in body["text"]


def test_an_unknown_srd_document_is_a_404_that_lists_the_real_ones(api):
    response = api.get("/api/srd/nope")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "nope" in detail
    assert "equipment" in detail


def test_an_unknown_srd_section_is_a_404(api):
    response = api.get("/api/srd/equipment", params={"slug": "nope"})
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_srd_section_carries_its_ancestry_for_a_breadcrumb(api):
    """The trail is sent rather than left for the client to derive.

    The client holds the table of contents, so it *could* walk it - but the server already
    knows the path, and a second lookup for something already computed is a way for the two
    to disagree.
    """
    body = api.get("/api/srd/rules-glossary", params={"slug": "prone-condition"}).json()
    assert [c["text"] for c in body["ancestors"]] == ["Rules Glossary", "Rules Definitions"]
    assert [c["slug"] for c in body["ancestors"]] == [
        "rules-glossary", "rules-definitions",
    ]


def test_srd_ancestry_excludes_the_section_itself(api):
    """The card titles the section, so repeating it as the last crumb would say it twice."""
    body = api.get("/api/srd/equipment", params={"slug": "coins"}).json()
    assert body["heading"] == "Coins"
    assert "Coins" not in [c["text"] for c in body["ancestors"]]


def test_a_whole_document_has_no_ancestry(api):
    """A file is the top of the tree, so there is nothing above it to link to."""
    assert api.get("/api/srd/equipment").json()["ancestors"] == []


def test_search_can_be_narrowed_to_the_rulebook(api):
    """The SRD shares the collection with the spells, so it needs its own filter.

    Without one, a rule is indistinguishable from a spell that has no school and a level of
    0 - and the recommender's pool would be able to admit it.
    """
    body = api.get("/api/search", params={"query": "", "mode": "text",
                                          "doc_type": "srd"}).json()
    assert [hit["name"] for hit in body["hits"]] == ["Cover"]
    assert body["where"] == {"doc_type": "srd"}
    assert body["hits"][0]["doc_type"] == "srd"
    assert body["hits"][0]["document"] == "playing-the-game"


def test_search_rejects_a_doc_type_it_does_not_have(api):
    response = api.get("/api/search", params={"query": "fire", "mode": "vector",
                                              "doc_type": "monster"})
    assert response.status_code == 400
    assert "Unknown doc_type" in response.json()["detail"]


def test_doc_type_all_reaches_the_rulebook(api):
    """``all`` is the value a rules search sends, so it has to mean the whole collection.

    It used to resolve to spells only, because ``spells_only`` defaults true and silently
    overrode it - so the one value that reads as "search everything" returned the narrowest
    set. The symptom was a rules tab that could never find a rule, with no error anywhere.
    """
    body = api.get("/api/search", params={"query": "", "mode": "text",
                                          "doc_type": "all"}).json()
    assert body["where"] is None
    assert {hit["doc_type"] for hit in body["hits"]} == {"spell", "item", "srd"}
    assert "Cover" in {hit["name"] for hit in body["hits"]}


def test_an_omitted_doc_type_still_means_spells_only(api):
    """The published default is unchanged: a caller that names no type gets the
    recommender's view, not the rulebook."""
    body = api.get("/api/search", params={"query": "", "mode": "text"}).json()
    assert body["where"] == {"doc_type": "spell"}
    assert {hit["doc_type"] for hit in body["hits"]} == {"spell"}


def test_class_context_lists_the_files_a_prompt_is_given(api):
    """The files spliced into a prompt as ``=== CHARACTER CONTEXT ===``, listed.

    Derived from ``context/classes/`` rather than hard-coded, so a class added to the
    directory appears here without an edit - and a file that does not exist is never
    offered as a link.
    """
    response = api.get("/api/class-context")
    assert response.status_code == 200
    files = response.json()
    paths = [found["path"] for found in files]
    assert "context/classes/warlock/base.md" in paths
    assert "context/classes/warlock/pact/tome.md" in paths
    assert "context/classes/warlock/subclass/celestial.md" in paths

    # The class-wide rules come first, then the pact, then the patron - the order a reader
    # should meet them in, and the order `prompts.context_files_for` loads them.
    assert paths.index("context/classes/warlock/base.md") < paths.index(
        "context/classes/warlock/pact/tome.md"
    )
    assert paths.index("context/classes/warlock/pact/tome.md") < paths.index(
        "context/classes/warlock/subclass/celestial.md"
    )


def test_a_class_context_name_is_the_phrase_the_prose_uses(api):
    """The name is what the front end searches generated prose for, so it has to be the
    phrase the prose actually writes - not the filename, which is a path segment.

    ``# Warlock - base class rules (D&D 5.5e / 2024)`` becomes ``Warlock``; the edition tag
    and the descriptive clause are provenance, not part of the name.
    """
    files = api.get("/api/class-context").json()
    by_path = {found["path"]: found for found in files}
    assert by_path["context/classes/warlock/base.md"]["name"] == "Warlock"
    assert by_path["context/classes/warlock/pact/tome.md"]["name"] == "Pact of the Tome"
    assert (
        by_path["context/classes/warlock/subclass/celestial.md"]["name"]
        == "Celestial Patron"
    )
    # The title keeps the whole heading, so a card can show what the file calls itself.
    assert by_path["context/classes/warlock/base.md"]["title"].startswith("Warlock - base")


def test_class_context_file_returns_the_text_verbatim(api):
    """Deterministic, like ``/api/srd/{name}``: no model sits between the file and the
    caller, so this cannot paraphrase a rule."""
    response = api.get("/api/class-context/classes/warlock/subclass/celestial.md")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Celestial Patron (D&D 5.5e / 2024)"
    assert body["path"] == "context/classes/warlock/subclass/celestial.md"
    # Not the SRD's badge: these files are our own summary of a class, and a summary must
    # not be able to look like a quotation.
    assert body["source"] == "class-context"
    assert "Healing Light" in body["text"]


def test_a_class_context_path_may_omit_the_classes_prefix(api):
    """The list gives a repo-relative path; a caller may also pass the tail of it."""
    body = api.get("/api/class-context/warlock/base.md").json()
    assert body["path"] == "context/classes/warlock/base.md"


def test_class_context_refuses_a_path_outside_the_directory(api):
    """The path arrives from a URL, so it is checked rather than trusted.

    Without this the endpoint would read any file on the machine and serve it as a rule.
    """
    for attempt in (
        "../../../../etc/passwd",
        "warlock/../../../AGENTS.md",
        "warlock/base.txt",
    ):
        response = api.get(f"/api/class-context/{attempt}")
        assert response.status_code == 404, attempt


def test_an_unknown_class_context_file_is_a_404(api):
    response = api.get("/api/class-context/warlock/nope.md")
    assert response.status_code == 404
    assert "nope.md" in response.json()["detail"]
