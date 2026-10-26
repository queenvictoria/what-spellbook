"""Tests for the retrieval layer in backend/libs/retrieval.py.

Covers character-sheet interpretation (level -> uniform slot level), the eligibility
lanes, chunk deduplication, and the index version guard.
"""

import pytest

from conftest import FakeDoc

from backend.libs import cache  # noqa: F401
from backend.libs import spells
from backend.libs import characters
from backend.libs import config
from backend.libs import indexing
from backend.libs import retrieval


# --- character sheet interpretation ---

LOIS = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Pact": "Tome",
    "Current Level": 5,
    "Known/Prepared Base Spells": "Eldritch Blast, Minor Illusion, Hex",
}


@pytest.mark.parametrize(
    "key", ["Current Level", "current_level", "Level", "level"]
)
def test_character_level_accepts_label_variants(key):
    assert characters.character_level({key: 5}) == 5


def test_character_level_parses_int_like_strings():
    assert characters.character_level({"Current Level": "Level 5"}) == 5
    assert characters.character_level({"Current Level": "5"}) == 5


def test_character_level_missing_is_none():
    assert characters.character_level({}) is None
    assert characters.character_level({"Current Level": ""}) is None
    assert characters.character_level({"Current Level": "unknown"}) is None


@pytest.mark.parametrize(
    "level,slot",
    [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (8, 4), (9, 5), (11, 5), (20, 5)],
)
def test_warlock_slot_level_follows_2024_progression(level, slot):
    """A level 5 Warlock has 3rd-level slots; all slots share one level."""
    assert characters.max_spell_level({"Class": "Warlock", "Current Level": level}) == slot


def test_max_spell_level_without_level_is_none():
    assert characters.max_spell_level({"Class": "Warlock"}) is None


def test_max_spell_level_for_lois_sheet():
    assert characters.max_spell_level(LOIS) == 3


# --- known spells ---

def test_known_spells_splits_comma_list():
    assert characters.known_spells(LOIS) == ["Eldritch Blast", "Minor Illusion", "Hex"]


def test_known_spells_accepts_yaml_sequence():
    assert characters.known_spells({"Prepared Spells": ["Hex", "Shield"]}) == ["Hex", "Shield"]


def test_known_spells_missing_is_empty():
    assert characters.known_spells({}) == []


def test_known_spells_ignores_blank_entries():
    assert characters.known_spells({"Prepared Spells": "Hex, , Shield"}) == ["Hex", "Shield"]


# --- deduplication ---

def test_dedupe_by_spell_keeps_one_chunk_per_spell():
    """A spell is chunked 2-12 times, so raw hits badly overstate the distinct set."""
    docs = [
        indexing.Document(page_content="a", metadata={"filename": "Fireball.md"}),
        indexing.Document(page_content="b", metadata={"filename": "Fireball.md"}),
        indexing.Document(page_content="c", metadata={"filename": "Haste.md"}),
    ]
    assert len(retrieval.dedupe_by_spell(docs)) == 2


def test_dedupe_by_spell_preserves_rank_order():
    docs = [
        indexing.Document(page_content="first", metadata={"filename": "A.md"}),
        indexing.Document(page_content="second", metadata={"filename": "B.md"}),
    ]
    assert [d.metadata["filename"] for d in retrieval.dedupe_by_spell(docs)] == ["A.md", "B.md"]


def test_dedupe_spells_case_insensitive():
    s1 = spells.Spell(name="Fireball", filename="a.md", level=3)
    s2 = spells.Spell(name="fireball", filename="b.md", level=3)
    assert len(retrieval.dedupe_spells([s1, s2])) == 1


# --- lanes ---

def test_exhaustive_lane_uses_metadata_query(fake_db):
    result = retrieval.exhaustive_lane(fake_db, spells.book_cantrip_filter())
    assert {s.name for s in result} == {"Acid Splash", "Fire Bolt"}


def test_exhaustive_lane_falls_back_when_get_unsupported(fake_db, monkeypatch):
    """Minimal stores may not implement get(); similarity search must still work."""
    def boom(**kwargs):
        raise TypeError("no get()")
    monkeypatch.setattr(fake_db, "get", boom, raising=False)
    result = retrieval.exhaustive_lane(fake_db, spells.book_cantrip_filter())
    assert result is not None


def test_exhaustive_lane_without_filter_is_empty(fake_db):
    assert retrieval.exhaustive_lane(fake_db, None) == []


def test_gather_returns_only_book_eligible_spells(fake_db):
    """Levelled spells are excluded entirely - a flat list invited mis-filing them."""
    bucket = retrieval.gather_spell_candidates(fake_db, character=LOIS)
    assert {s.name for s in bucket["cantrips"]} == {"Acid Splash", "Fire Bolt"}
    assert {s.name for s in bucket["rituals"]} == {"Detect Magic"}


def test_gather_excludes_known_spells_from_lanes(fake_db):
    retrieval.gather_spell_candidates(fake_db, character=LOIS, query="x")
    lane_where = [w for w in fake_db.get_calls if w]
    assert any({"spell_name": {"$nin": ["Eldritch Blast", "Minor Illusion", "Hex"]}} in
               w.get("$and", []) for w in lane_where)


def test_gather_skips_ranking_lane_without_query(fake_db):
    bucket = retrieval.gather_spell_candidates(fake_db, character=LOIS, query=None)
    assert bucket["ranked"] == []


def test_gather_ranks_candidates_against_the_scenario(fake_db):
    """The scenario orders the shortlist, but cannot change what is legal."""
    retrieval.gather_spell_candidates(fake_db, character=LOIS, query="a bridge")
    assert fake_db.retriever.queries

def test_gather_returns_expected_bucket_keys(fake_db):
    bucket = retrieval.gather_spell_candidates(fake_db, character=LOIS)
    assert set(bucket) == {"cantrips", "rituals", "ranked"}


# --- rendering ---

def _bucket():
    return {
        "cantrips": [spells.Spell(name="Acid Splash", filename="a.md", level=0)],
        "rituals": [spells.Spell(name="Detect Magic", filename="d.md", level=1, is_ritual=True)],
        "ranked": [],
    }


def test_format_pool_states_the_pick_counts():
    pool = retrieval.format_pool(_bucket(), 3)
    assert str(spells.BOOK_CANTRIP_PICKS) in pool
    assert str(spells.BOOK_RITUAL_PICKS) in pool


def test_format_pool_separates_the_two_book_lanes():
    pool = retrieval.format_pool(_bucket(), 3)
    assert "CANTRIP OPTIONS" in pool
    assert "LEVEL 1 RITUAL OPTIONS" in pool


def test_format_pool_marks_both_lanes_as_the_only_permitted_source():
    """Mis-filing a levelled spell as a pick was the observed model failure."""
    pool = retrieval.format_pool(_bucket(), 3)
    assert pool.count("the ONLY") >= 2


def test_format_pool_never_lists_levelled_spells_as_options():
    """A levelled spell in the pool is what caused Misty Step to be picked."""
    pool = retrieval.format_pool(_bucket(), 3)
    assert "Misty Step" not in pool
    assert "Fireball" not in pool


def test_format_pool_states_uniform_slot_level():
    assert "level 3" in retrieval.format_pool(_bucket(), 3)


def test_format_pool_handles_empty_bucket():
    assert "no spells matched" in retrieval.format_pool(
        {"cantrips": [], "rituals": [], "ranked": []}, 3
    )


def test_format_pool_includes_ranked_hint_when_present():
    bucket = _bucket()
    bucket["ranked"] = [FakeDoc(page_content="x", spell_name="Detect Magic", level=1)]
    assert "SCENARIO-MATCHED" in retrieval.format_pool(bucket, 3, limit=5)


def test_format_full_text_caps_the_shortlist():
    bucket = {"cantrips": [], "rituals": [], "ranked": [
        FakeDoc(page_content=f"text {i}", filename=f"{i}.md") for i in range(20)
    ]}
    rendered = retrieval.format_full_text(bucket, limit=3)
    assert rendered.count("---") == 2


# --- index version guard ---

def test_db_is_valid_false_without_index(tmp_path):
    assert indexing.db_is_valid(str(tmp_path / "absent")) is False


def test_db_is_valid_false_on_unreadable_index(tmp_path, monkeypatch):
    """A directory without a usable index must not be treated as valid.

    get_embeddings is stubbed so this test cannot construct a real client and leave
    the module-level cache populated for later tests.
    """
    monkeypatch.setattr(indexing, "get_embeddings", lambda: None)
    (tmp_path / "chroma.sqlite3").write_bytes(b"not a database")
    assert indexing.db_is_valid(str(tmp_path)) is False


def test_index_version_is_recorded_in_constants():
    """The guard compares against this constant, so it must exist and be an int."""
    assert isinstance(config.INDEX_VERSION, int)


def test_retrieval_k_is_large_enough_for_the_book_lanes():
    """There are 48 cantrips; a small k would silently truncate the pool."""
    assert config.RETRIEVAL_K >= 48


def test_retrieve_falls_back_to_retriever(fake_db):
    docs = retrieval.retrieve(fake_db, "query", {"level": 3}, k=5)
    assert docs == fake_db.docs
    assert fake_db.as_retriever_calls[-1]["filter"] == {"level": 3}
