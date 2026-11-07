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


# --- the SRD as indexed text ---


def test_srd_documents_are_one_row_per_section():
    """The rulebook is indexed by heading, because a rule's identity is its heading."""
    docs = indexing._srd_documents()
    assert docs
    assert all(doc.metadata["doc_type"] == "srd" for doc in docs)
    assert all(doc.metadata["is_spell"] is False for doc in docs)


def test_srd_rows_carry_the_keys_the_spell_filters_read():
    """Chroma cannot filter on a missing key, so an SRD row must carry every field.

    A row without ``level`` would be invisible to a ``$lte`` clause and would silently
    vanish from a search that should have excluded it.
    """
    doc = indexing._srd_documents()[0]
    for key in ("source", "filename", "spell_name", "level", "school", "classes",
                "ritual", "is_spell", "doc_type", "document", "slug"):
        assert key in doc.metadata, key


def test_srd_rows_are_not_reported_as_cantrips():
    """``level`` is 0 as a placeholder, and the heading's own depth is kept separately.

    Overloading ``level`` would make a spell-level filter mean two different things.
    """
    doc = indexing._srd_documents()[0]
    assert doc.metadata["level"] == 0
    assert doc.metadata["heading_level"] > 1


def test_a_long_chapter_is_split_into_several_chunks():
    """A 1,750-line class chapter as one embedding would match everything weakly."""
    docs = indexing._srd_documents()
    wizard = [doc for doc in docs if doc.metadata["spell_name"] == "Wizard"]
    assert len(wizard) > 1
    assert all(len(doc.page_content) <= indexing.SRD_CHUNK_SIZE + 200 for doc in wizard)


def test_a_chunk_repeats_its_heading_so_it_can_be_read_alone():
    """A chunk split away from its heading still has to say what it is about."""
    doc = indexing._srd_documents()[0]
    assert doc.metadata["spell_name"] in doc.page_content
    assert doc.metadata["document_title"] in doc.page_content


def test_a_missing_srd_directory_is_not_an_error(tmp_path):
    """The spell corpus is the index's reason to exist; a checkout without the vendored
    rules should still build a usable index rather than refuse."""
    assert indexing._srd_documents(tmp_path / "absent") == []


def test_the_srd_is_not_in_the_book_pool(fake_db):
    """The invariant the doc-type marker exists for.

    An SRD row is ``is_spell=False``, exactly like a magic item, so a filter that asked only
    for "not a spell" would hand the recommender the rulebook.
    """
    cantrips = retrieval.exhaustive_lane(fake_db, spells.book_cantrip_filter())
    rituals = retrieval.exhaustive_lane(fake_db, spells.book_ritual_filter())
    names = {spell.name for spell in cantrips + rituals}
    assert "Cover" not in names
    assert "Armblade" not in names


# --- the SRD context lane for the recommender ---


class _SrdIndex:
    """A store whose similarity search returns SRD rows, for the context lane."""

    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def similarity_search_with_score(self, query, k=4, filter=None, **kwargs):
        self.filters.append(filter)
        return [(FakeDoc(**row), 0.1 * index) for index, row in enumerate(self.rows[:k])]

    def get(self, where=None, include=None, **kwargs):
        return {"metadatas": self.rows, "ids": [r["filename"] for r in self.rows]}


def _rule_row(name, document, slug, text):
    return {"spell_name": name, "filename": document, "doc_type": "srd",
            "document": document, "slug": slug, "level": 0, "is_spell": False,
            "_text": text}


def test_the_srd_context_lane_asks_only_for_rules():
    """The recommender's pool is filtered separately; this lane is grounding, not picks."""
    db = _SrdIndex([_rule_row("Grappled", "rules-glossary", "grappled-condition", "text")])
    retrieval.gather_srd_context(db, "we are grappled")
    assert db.filters == [{"doc_type": "srd"}]


def test_the_srd_context_lane_dedupes_sections():
    db = _SrdIndex([
        _rule_row("Grappled", "rules-glossary", "grappled-condition", "a"),
        _rule_row("Grappled", "rules-glossary", "grappled-condition", "b"),
    ])
    assert len(retrieval.gather_srd_context(db, "grappled")) == 1


def test_the_srd_context_lane_returns_nothing_for_an_empty_scenario():
    """No scenario means nothing to ground, and an embedding call would be wasted."""
    db = _SrdIndex([_rule_row("Cover", "rules-glossary", "cover", "text")])
    assert retrieval.gather_srd_context(db, "   ") == []
    assert db.filters == []


def test_the_srd_context_lane_degrades_rather_than_raising():
    """A recommendation must still be produced without rules grounding.

    It is a degradation, not a failure - so a store that cannot answer must not take the
    whole run down with it.
    """
    class Broken:
        def similarity_search_with_score(self, *args, **kwargs):
            raise RuntimeError("index unavailable")

    assert retrieval.gather_srd_context(Broken(), "we are grappled") == []


def test_the_srd_context_block_labels_each_section_with_its_source():
    """The model is told to cite the rule it used, so a bare paragraph gives it nothing."""
    rendered = retrieval.format_srd_context([
        {"name": "Cover", "document": "rules-glossary", "slug": "cover", "text": "Half Cover"},
    ])
    assert "rules-glossary > Cover" in rendered
    assert "Half Cover" in rendered


def test_an_empty_srd_context_renders_as_nothing():
    """A heading with nothing under it reads as "the rules are missing"."""
    assert retrieval.format_srd_context([]) == ""
    assert retrieval.format_srd_context(None) == ""


def test_building_over_a_live_index_does_not_double_it(tmp_path, monkeypatch):
    """``Chroma.from_documents`` *adds* to an existing collection rather than replacing it.

    ``ensure_db`` resets first, but a direct ``build_index`` call does not - and a doubled
    index is invisible until a count looks wrong. This was found live: calling
    ``build_index`` twice reported 7302 chunks for a 3651-chunk corpus.
    """
    reset = []
    monkeypatch.setattr(indexing, "reset_db", lambda db_dir: reset.append(db_dir))
    monkeypatch.setattr(indexing, "get_embeddings", lambda: None)
    monkeypatch.setattr(indexing.Chroma, "from_documents",
                        classmethod(lambda cls, *a, **k: "db"))

    docs = tmp_path / "spells"
    docs.mkdir()
    for index in range(11):
        (docs / f"Spell {index}.md").write_text(
            f"# Spell {index}\n\n**Casting Time:** Action\n", encoding="utf-8"
        )

    indexing.build_index(docs, str(tmp_path / "db"), srd_path=tmp_path / "no-srd")
    assert reset == [str(tmp_path / "db")]
