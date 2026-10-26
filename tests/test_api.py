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


# --- rules ---


def test_rules_answers_are_grounded_and_cached(api, monkeypatch):
    """The second ask must be answered from stored rule text, not re-fetched.

    ``rules.fetch_page`` is stubbed rather than ``rules.gather`` on purpose: replacing
    ``gather`` would replace the cache lookup this test exists to verify.
    """
    fetched = []

    def fake_fetch_page(url, **kwargs):
        fetched.append(url)
        return "## Cover\nWalls and trees provide cover."

    monkeypatch.setattr(rules, "fetch_page", fake_fetch_page)
    monkeypatch.setattr(
        rules, "candidate_pages",
        lambda *a, **k: ["https://5e24srd.com/playing-the-game/combat.html"],
    )
    monkeypatch.setattr(
        "backend.libs.llm.invoke",
        lambda *a, **k: "Walls and trees provide cover. Note the table is not shown here.",
    )

    first = api.get("/api/rules", params={"question": "how does cover work"}).json()
    assert first["source"] == "rules"
    assert first["citations"] == ["https://5e24srd.com/playing-the-game/combat.html"]
    assert first["from_cache"] is False
    assert len(fetched) == 1

    second = api.get("/api/rules", params={"question": "how does cover work"}).json()
    assert second["from_cache"] is True
    assert second["answer"] == first["answer"]
    assert len(fetched) == 1, "the second ask must not have hit the network"


def test_rules_reports_a_missing_rule_as_404(api, monkeypatch):
    def fake_gather(question, **kwargs):
        raise rules.RulesUnavailable("the SRD does not define a Short Rest")

    monkeypatch.setattr(rules, "gather", fake_gather)
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
