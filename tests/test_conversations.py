"""Stored ask/chat conversations: the thread store, the service wiring and the API.

The gap this covers: ``/?`` and the contextual menu cached *one question* each, and
``/c`` and ``/ask`` stored nothing at all. A follow-up ("and a grapple?") had no subject
of its own, and nothing could be listed or read back as a conversation.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.libs import conversations, service

from conftest import BOOKS_ANSWER, FakeDB, FakeLLM

LOIS = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Current Level": 5,
    "Party": "Barbarian, Fighter, Druid",
    "Passive Scores": "Perception 12, Insight 15, Investigation 13",
    "Armor Class": 14,
}

SCENARIO = "A rust monster eats the fighter's plate armour mid-fight."


# --- the store ---


def test_a_turn_is_stored_and_read_back(tmp_path):
    turn = conversations.Turn(question="how does cover work", answer="Walls give cover.",
                              source="rules", citations=["context/srd/x.md"])
    conversation = conversations.append("Lois", "rules", "how does cover work", turn,
                                        cache_dir=tmp_path)

    assert conversation.id == conversations.thread_id("rules", "how does cover work")
    stored = conversations.load("Lois", "rules", "how does cover work", tmp_path)
    assert stored is not None
    assert [t.question for t in stored.turns] == ["how does cover work"]
    assert stored.turns[0].citations == ["context/srd/x.md"]


def test_a_follow_up_joins_the_thread_it_followed(tmp_path):
    """The opening question identifies the thread, so a follow-up must not start a new one."""
    conversations.append("Lois", "rules", "how does cover work",
                         conversations.Turn(question="how does cover work", answer="A",
                                            source="rules"), cache_dir=tmp_path)
    conversation = conversations.append(
        "Lois", "rules", "how does cover work",
        conversations.Turn(question="and a grapple?", answer="B", source="rules"),
        cache_dir=tmp_path,
    )

    assert len(conversation.turns) == 2
    assert [t.question for t in conversation.turns] == ["how does cover work", "and a grapple?"]
    assert len(conversations.list_threads(tmp_path)) == 1


def test_the_same_words_asked_of_two_surfaces_are_two_threads(tmp_path):
    """The kind is part of the key: a sheet question and a rules question differ."""
    conversations.append("Lois", "rules", "what is a spell attack",
                         conversations.Turn(question="what is a spell attack", answer="A",
                                            source="rules"), cache_dir=tmp_path)
    conversations.append("Lois", "character", "what is a spell attack",
                         conversations.Turn(question="what is a spell attack", answer="B",
                                            source="model"), cache_dir=tmp_path)

    assert len(conversations.list_threads(tmp_path)) == 2
    assert len(conversations.list_threads(tmp_path, kind="rules")) == 1
    assert conversations.load("Lois", "rules", "what is a spell attack",
                              tmp_path).turns[0].answer == "A"


def test_threads_are_listed_newest_first_by_update(tmp_path):
    """A thread continued today sorts above one that merely started today."""
    conversations.append("Lois", "rules", "first",
                         conversations.Turn(question="first", answer="A", source="rules",
                                            asked_at="2024-01-01T00:00:00+00:00"),
                         cache_dir=tmp_path)
    conversations.append("Lois", "rules", "second",
                         conversations.Turn(question="second", answer="B", source="rules",
                                            asked_at="2024-01-02T00:00:00+00:00"),
                         cache_dir=tmp_path)
    # Continue the older thread, which must move it to the top.
    conversations.append("Lois", "rules", "first",
                         conversations.Turn(question="more", answer="C", source="rules"),
                         cache_dir=tmp_path)

    listed = conversations.list_threads(tmp_path)
    assert [c.opening for c in listed] == ["first", "second"]


def test_a_thread_is_found_by_id_path_or_fragment(tmp_path):
    conversation = conversations.append(
        "Lois", "rules", "how does cover work",
        conversations.Turn(question="how does cover work", answer="A", source="rules"),
        cache_dir=tmp_path,
    )

    assert conversations.find(conversation.id, tmp_path).id == conversation.id
    assert conversations.find("cover", tmp_path).id == conversation.id
    assert conversations.find(str(conversation.path), tmp_path).id == conversation.id
    assert conversations.find("nothing like this", tmp_path) is None


def test_a_thread_from_an_older_schema_is_refused(tmp_path):
    """Half-reading a thread would report an empty conversation as a stored one."""
    path = conversations.path_for("Lois", "rules", "how does cover work", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": conversations.SCHEMA_VERSION + 1,
        "id": "x", "kind": "rules", "character": "Lois", "opening": "how does cover work",
        "turns": [{"question": "q", "answer": "a", "source": "rules"}],
    }), encoding="utf-8")

    assert conversations.load("Lois", "rules", "how does cover work", tmp_path) is None
    assert conversations.list_threads(tmp_path) == []


def test_a_thread_with_no_turns_is_not_a_conversation(tmp_path):
    path = conversations.path_for("Lois", "rules", "how does cover work", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": conversations.SCHEMA_VERSION,
        "id": "x", "kind": "rules", "character": "Lois", "opening": "how does cover work",
        "turns": [],
    }), encoding="utf-8")

    assert conversations.load("Lois", "rules", "how does cover work", tmp_path) is None


def test_a_broken_file_does_not_raise(tmp_path):
    """A conversation is a record of an answer; losing the record must not lose the answer."""
    path = conversations.path_for("Lois", "rules", "how does cover work", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert conversations.load("Lois", "rules", "how does cover work", tmp_path) is None
    assert conversations.list_threads(tmp_path) == []


def test_the_history_block_carries_only_the_recent_turns():
    """A thread is unbounded and a prompt is not, so only the tail is carried."""
    turns = [conversations.Turn(question=f"q{i}", answer=f"a{i}", source="rules")
             for i in range(10)]
    block = conversations.history_block(turns, limit=2)

    assert "q9" in block and "q8" in block
    assert "q0" not in block
    assert conversations.history_block([]) == ""


# --- the service ---


@pytest.fixture
def svc(tmp_path):
    return service.SpellbookService(
        FakeDB(), dict(LOIS), backend=FakeLLM("Walls give cover."),
        cache_dir=str(tmp_path / "cache"),
    )


def test_asking_a_rule_records_a_conversation(svc):
    answer = svc.ask_rules("how does cover work")

    assert answer.thread_id
    stored = svc.conversation(answer.thread_id)
    assert stored is not None
    assert stored.kind == "rules"
    assert [t.question for t in stored.turns] == ["how does cover work"]
    assert stored.turns[0].source == "rules"


def test_a_follow_up_is_read_in_context(svc):
    """The second question must reach the model with the first exchange beside it."""
    first = svc.ask_rules("how does cover work")
    svc.ask_rules("and a grapple?", thread_id=first.thread_id)

    prompt = svc.llm.prompts[-1]
    assert "EARLIER IN THIS CONVERSATION" in prompt
    assert "how does cover work" in prompt
    assert len(svc.conversation(first.thread_id).turns) == 2


def test_a_first_question_carries_no_history(svc):
    svc.ask_rules("how does cover work")
    assert "EARLIER IN THIS CONVERSATION" not in svc.llm.prompts[-1]


def test_a_sheet_lookup_is_recorded_too(svc):
    """A lookup is an answer like any other, and a follow-up may refer to it."""
    answer = svc.ask_character("passive perception")

    stored = svc.conversation(answer.thread_id)
    assert stored.kind == "character"
    assert stored.turns[0].source == "sheet"
    assert stored.turns[0].field_name == "Passive Scores"


def test_a_selection_is_recorded_under_its_own_kind(svc):
    answer = svc.ask_rules_contextual("2 beams")
    stored = svc.conversation(answer.thread_id)
    assert stored.kind == "selection"


def test_a_refinement_is_recorded_against_its_scenario(svc):
    generation = svc.scenario(SCENARIO)
    refined = svc.refine("what if it has fire resistance?", generation)

    assert refined.thread_id
    stored = svc.conversation(refined.thread_id)
    assert stored.kind == "refine"
    assert stored.opening == SCENARIO
    assert stored.turns[0].question == "what if it has fire resistance?"


def test_a_repeated_question_replays_rather_than_re_asking(svc):
    """The rules cache already answers this; the conversation must not defeat it."""
    first = svc.ask_rules("how does cover work")
    calls = len(svc.llm.prompts)
    second = svc.ask_rules("how does cover work")

    assert len(svc.llm.prompts) == calls, "the repeat must not have reached the model"
    assert second.from_cache is True
    assert second.thread_id == first.thread_id
    # And the replay is recorded, so the thread shows the exchange was revisited.
    assert len(svc.conversation(first.thread_id).turns) == 2


def test_a_repeated_character_question_replays_rather_than_re_asking(svc):
    """The character surface has no cache of its own; the thread is what makes it replay."""
    first = svc.ask_character("why do I have two Light spells?")
    calls = len(svc.llm.prompts)
    second = svc.ask_character("why do I have two Light spells?")

    assert len(svc.llm.prompts) == calls, "the repeat must not have reached the model"
    assert second.from_cache is True
    assert second.thread_id == first.thread_id
    assert len(svc.conversation(first.thread_id).turns) == 2


def test_an_edited_sheet_invalidates_a_replayed_character_answer(svc):
    """Same name and level, different spells: the stored answer no longer applies."""
    first = svc.ask_character("why do I have two Light spells?")
    calls = len(svc.llm.prompts)

    svc.character["Known/Prepared Base Spells"] = "Eldritch Blast, Hex"
    second = svc.ask_character("why do I have two Light spells?")

    assert len(svc.llm.prompts) == calls + 1, "an edited sheet must be asked again"
    assert second.from_cache is False
    # The thread is still the same conversation, so the change is visible in its history.
    assert second.thread_id == first.thread_id
    assert len(svc.conversation(first.thread_id).turns) == 2


def test_a_repeated_refinement_replays_rather_than_re_asking(svc):
    """A refinement is expensive, and the same words against the same books is a repeat."""
    generation = svc.scenario(SCENARIO)
    first = svc.refine("what if it has fire resistance?", generation)
    calls = len(svc.llm.prompts)
    second = svc.refine("what if it has fire resistance?", generation)

    assert len(svc.llm.prompts) == calls, "the repeat must not have reached the model"
    assert second.from_cache is True
    assert second.thread_id == first.thread_id
    # The books are re-split from the stored prose, so a replay is still renderable.
    assert [b.name for b in second.books] == [b.name for b in first.books]
    # And the replay is recorded as one, so the thread shows it was revisited.
    assert [t.from_cache for t in svc.conversation(first.thread_id).turns] == [False, True]


def test_a_refinement_against_different_books_is_not_replayed(svc):
    """The same words refining different books is a different request."""
    first = svc.scenario(SCENARIO)
    svc.refine("what if it has fire resistance?", first)

    other = svc.scenario("A dragon strafes the party from above.")
    calls = len(svc.llm.prompts)
    svc.refine("what if it has fire resistance?", other)

    assert len(svc.llm.prompts) == calls + 1, "different books must be refined afresh"


def test_conversations_are_scoped_to_the_character(tmp_path):
    """Two characters asking the same question are two conversations."""
    cache = str(tmp_path / "cache")
    lois = service.SpellbookService(FakeDB(), dict(LOIS), backend=FakeLLM("A"),
                                    cache_dir=cache)
    other = service.SpellbookService(FakeDB(), dict(LOIS, Name="Mira"), backend=FakeLLM("B"),
                                     cache_dir=cache)

    lois.ask_rules("how does cover work")
    other.ask_rules("how does cover work")

    assert len(lois.conversations()) == 1
    assert len(other.conversations()) == 1
    assert lois.conversations()[0].character == "Lois"
    assert other.conversations()[0].character == "Mira"


def test_no_character_means_no_conversation(tmp_path):
    """A thread is keyed on the character, so there is nothing to key it on."""
    svc = service.SpellbookService(FakeDB(), {}, backend=FakeLLM("A"),
                                   cache_dir=str(tmp_path / "cache"))
    assert svc.conversations() == []
    assert svc.conversation("anything") is None


# --- the API ---


@pytest.fixture
def api(tmp_path, monkeypatch):
    app = create_app(vector_db=FakeDB(), backend=FakeLLM("Walls give cover."),
                     character_name="lois", cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data",
                        lambda name, **kw: dict(LOIS))
    return TestClient(app)


def test_the_api_returns_a_thread_id(api):
    body = api.get("/api/rules", params={"question": "how does cover work"}).json()
    assert body["thread_id"]


def test_the_api_continues_a_thread(api):
    first = api.get("/api/rules", params={"question": "how does cover work"}).json()
    second = api.get("/api/rules", params={
        "question": "and a grapple?", "thread_id": first["thread_id"],
    }).json()

    assert second["thread_id"] == first["thread_id"]
    stored = api.get(f"/api/conversations/{first['thread_id']}").json()
    assert [t["question"] for t in stored["turns"]] == ["how does cover work", "and a grapple?"]


def test_the_api_lists_conversations(api):
    api.get("/api/rules", params={"question": "how does cover work"})
    api.get("/api/character/ask", params={"question": "passive perception"})

    listed = api.get("/api/conversations").json()
    assert {row["kind"] for row in listed} == {"rules", "character"}
    assert all(row["turn_count"] == 1 for row in listed)

def test_the_api_filters_conversations_by_kind(api):
    api.get("/api/rules", params={"question": "how does cover work"})
    api.get("/api/character/ask", params={"question": "passive perception"})

    listed = api.get("/api/conversations", params={"kind": "character"}).json()
    assert [row["kind"] for row in listed] == ["character"]


def test_an_unknown_conversation_is_404(api):
    assert api.get("/api/conversations/nothing-here").status_code == 404


def test_a_conversation_can_be_found_by_a_fragment(api):
    api.get("/api/rules", params={"question": "how does cover work"})
    body = api.get("/api/conversations/cover").json()
    assert body["opening"] == "how does cover work"


def test_the_refine_endpoint_returns_a_thread_id(api):
    api.post("/api/scenario", json={"scenario": SCENARIO})
    body = api.post("/api/ask", params={"scenario": SCENARIO},
                    json={"question": "what if it has fire resistance?"}).json()

    assert body["thread_id"]
    stored = api.get(f"/api/conversations/{body['thread_id']}").json()
    assert stored["kind"] == "refine"
    assert stored["opening"] == SCENARIO


def test_the_contextual_endpoint_returns_a_thread_id(api):
    body = api.get("/api/rules/contextual", params={"selected_text": "2 beams"}).json()
    assert body["thread_id"]
    stored = api.get(f"/api/conversations/{body['thread_id']}").json()
    assert stored["kind"] == "selection"


# --- the vector lane as the last resort for a rules question ---


def test_a_question_no_heading_names_falls_back_to_the_index(svc, monkeypatch):
    """The third path, and the only one that is not heading-anchored.

    A question phrased in words the SRD does not use in a *heading* is refused by both
    anchored paths even when the SRD discusses it at length. The index lane finds the
    section by similarity instead - and the answer is still labelled ``rules-inferred``,
    because a similarity hit is not a quotation.
    """
    from backend.libs import rules

    def refuse(*args, **kwargs):
        raise rules.RulesUnavailable("no heading names this")

    monkeypatch.setattr(rules, "gather", refuse)
    monkeypatch.setattr(rules, "gather_inferred", refuse)

    answer = svc.ask_rules("how do I stop someone running past me")
    assert answer.source == "rules-inferred"
    assert answer.citations


def test_the_index_lane_is_not_reached_when_a_heading_answers(svc, monkeypatch):
    """The anchored paths are the precise ones and must keep winning.

    Reaching for the index first would replace a quoted rule with a similar-looking
    paragraph, which is the failure the anchor exists to prevent.
    """
    from backend.libs import rules

    def refuse(*args, **kwargs):
        raise rules.RulesUnavailable("the index lane must not be reached")

    monkeypatch.setattr(rules, "gather_from_index", refuse)
    answer = svc.ask_rules("how does cover work")
    assert answer.source == "rules"
