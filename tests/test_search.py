"""Searching the vector index: filters, modes and the shapes they return.

The store is a fake, but the *filter clauses* are real - they are built by the same code
the API calls, and the fake's ``where`` matcher understands the operators Chroma does. That
matters more here than elsewhere: the class filter is an ``$or`` over exact class-list
strings because the field is one comma-joined value, and a test that stubbed the clause
would not notice it regressing to an ``$in`` that silently matches nothing.
"""

from __future__ import annotations

import pytest

from backend.libs import search

from conftest import FakeDB, FakeDoc


class SearchDB(FakeDB):
    """A catalogue with the shapes the real index has: multi-class lists, items, chunks.

    ``FakeDB``'s catalogue is one row per spell with a single class, which cannot express
    the two things this module exists to get right - a class list that is a joined string,
    and several chunks per spell.
    """

    CATALOGUE = [
        {"filename": "Fire Bolt.md", "spell_name": "Fire Bolt", "level": 0,
         "ritual": False, "is_spell": True, "doc_type": "spell", "school": "Evocation",
         "classes": "Sorcerer, Wizard"},
        {"filename": "Fire Bolt.md", "spell_name": "Fire Bolt", "level": 0,
         "ritual": False, "is_spell": True, "doc_type": "spell", "school": "Evocation",
         "classes": "Sorcerer, Wizard"},
        {"filename": "Fireball.md", "spell_name": "Fireball", "level": 3,
         "ritual": False, "is_spell": True, "doc_type": "spell", "school": "Evocation",
         "classes": "Sorcerer, Wizard"},
        {"filename": "Cure Wounds.md", "spell_name": "Cure Wounds", "level": 1,
         "ritual": False, "is_spell": True, "doc_type": "spell", "school": "Abjuration",
         "classes": "Bard, Cleric, Druid"},
        {"filename": "Detect Magic.md", "spell_name": "Detect Magic", "level": 1,
         "ritual": True, "is_spell": True, "doc_type": "spell", "school": "Divination",
         "classes": "Bard, Cleric, Wizard"},
        {"filename": "Armblade.md", "spell_name": "Armblade", "level": -1,
         "ritual": False, "is_spell": False, "doc_type": "item", "school": "",
         "classes": ""},
        # An SRD row. It shares the collection with the spells and carries the same keys, so
        # a filter that forgot ``doc_type`` would return it - which is the failure the
        # doc-type tests exist to catch.
        {"filename": "playing-the-game", "spell_name": "Cover", "level": 0,
         "ritual": False, "is_spell": False, "doc_type": "srd", "school": "",
         "classes": "", "document": "playing-the-game", "slug": "cover"},
    ]

    def get(self, where=None, include=None, **kwargs):
        self.get_calls.append(where)
        rows = [r for r in self.CATALOGUE if self._matches(r, where)]
        payload = {"metadatas": rows, "ids": [r["filename"] for r in rows]}
        if include and "documents" in include:
            payload["documents"] = [f"{r['spell_name']} deals damage." for r in rows]
        return payload

    def similarity_search_with_score(self, query, k=4, filter=None, **kwargs):
        """Score by word overlap, so a query's words decide the order.

        A real embedding is not available in a unit test, and a canned result list would
        make the ordering assertions meaningless - the point of the vector and hybrid tests
        is that the *query* changes the order.
        """
        rows = [r for r in self.CATALOGUE if self._matches(r, filter)]
        words = set(query.casefold().split())

        def score(row):
            text = f"{row['spell_name']} {row['school']}".casefold()
            return 1.0 - 0.1 * sum(1 for word in words if word in text)

        ranked = sorted(rows, key=score)
        return [
            (FakeDoc(f"{row['spell_name']} deals damage.", **row), score(row))
            for row in ranked[:k]
        ]


@pytest.fixture
def db():
    return SearchDB()


# --- filters ---


def test_a_class_filter_matches_a_joined_class_list(db):
    """The bug this guards: ``$in`` compares the whole value, so it misses "Sorcerer, Wizard".

    The index stores the class list as one comma-joined string, so a filter for Wizard has
    to be an ``$or`` over the exact combinations that name it. An ``$in`` would return only
    the spells whose list is *exactly* "Wizard" - which is most of them missing, silently.
    """
    result = search.search(db, "", mode="text", classes=["Wizard"])
    assert {hit.name for hit in result.hits} == {"Fire Bolt", "Fireball", "Detect Magic"}


def test_a_class_filter_requires_any_of_the_named_classes(db):
    """Repeatable and OR-ed, so "Bard or Cleric" is one request rather than two."""
    result = search.search(db, "", mode="text", classes=["Cleric", "Druid"])
    assert {hit.name for hit in result.hits} == {"Cure Wounds", "Detect Magic"}


def test_a_class_the_index_never_uses_matches_nothing(db):
    """A filter must never widen the search.

    Dropping an unsatisfiable clause would quietly return the whole collection, which is
    the one outcome a filter cannot have. The result says why instead.
    """
    result = search.search(db, "fire", mode="vector", classes=["Artificer"])
    assert result.hits == []
    assert result.where is None
    assert "lists that class" in result.note


def test_level_and_ritual_filters_combine(db):
    result = search.search(db, "", mode="text", level_min=1, level_max=1, ritual=True)
    assert [hit.name for hit in result.hits] == ["Detect Magic"]


def test_magic_items_are_excluded_by_default_and_included_on_request(db):
    """The collection holds 22 magic items alongside the spells, at level -1."""
    assert "Armblade" not in {hit.name for hit in search.search(db, "", mode="text").hits}
    everything = search.search(db, "", mode="text", spells_only=False)
    assert "Armblade" in {hit.name for hit in everything.hits}


def test_an_item_reports_no_level_rather_than_minus_one(db):
    """-1 is the index's marker for "not a spell", not a level, and must not leak out."""
    item = next(
        hit for hit in search.search(db, "", mode="text", spells_only=False).hits
        if hit.name == "Armblade"
    )
    assert item.level is None
    assert item.level_label == "Not a spell"


# --- modes ---


def test_text_mode_collapses_chunks_into_one_hit_per_spell(db):
    """Fire Bolt is two chunks; a raw listing would show it twice and read as a bug."""
    result = search.search(db, "", mode="text")
    names = [hit.name for hit in result.hits]
    assert names.count("Fire Bolt") == 1
    # Four spells plus the item, which is excluded by default.
    assert result.total_matching == 4


def test_text_mode_requires_every_word_by_default(db):
    """A match on one common word is the noise this mode exists to cut through."""
    strict = search.search(db, "fire bolt", mode="text")
    assert [hit.name for hit in strict.hits] == ["Fire Bolt"]

    relaxed = search.search(db, "fire bolt", mode="text", all_terms=False)
    assert {hit.name for hit in relaxed.hits} == {"Fire Bolt", "Fireball"}


def test_text_mode_explains_an_and_that_found_nothing(db):
    """An empty page that reads as a broken index is worse than a sentence saying why."""
    result = search.search(db, "fire wounds", mode="text")
    assert result.hits == []
    assert "all 2 words" in result.note


def test_text_mode_accepts_an_empty_query_to_browse(db):
    """The way to check a filter selects what you think it does."""
    result = search.search(db, "", mode="text", classes=["Bard"])
    assert result.total_matching == 2


def test_vector_mode_needs_text_to_embed(db):
    with pytest.raises(ValueError, match="needs some text"):
        search.search(db, "", mode="vector")


def test_hybrid_ranks_word_matches_first(db):
    """The point of the mode is to see what a keyword would have promoted."""
    result = search.search(db, "fire", mode="hybrid")
    assert result.hits[0].name == "Fire Bolt"
    assert result.hits[0].terms_matched == 1


def test_a_vector_search_reports_how_many_the_filter_admits(db):
    """There is no relevance threshold, so the useful number is the filter's width."""
    result = search.search(db, "fire", mode="vector", classes=["Wizard"])
    assert result.total_matching == 3


# --- paging and validation ---


def test_offset_pages_through_the_ordered_hits(db):
    first = search.search(db, "", mode="text", limit=2)
    second = search.search(db, "", mode="text", limit=2, offset=2)
    assert len(first.hits) == 2
    assert not ({h.name for h in first.hits} & {h.name for h in second.hits})


def test_an_unknown_mode_is_rejected(db):
    with pytest.raises(ValueError, match="Unknown search mode"):
        search.search(db, "fire", mode="fuzzy")


def test_an_inverted_level_range_is_rejected(db):
    with pytest.raises(ValueError, match="level_min is greater"):
        search.search(db, "fire", mode="text", level_min=5, level_max=2)


def test_a_limit_outside_the_cap_is_rejected(db):
    with pytest.raises(ValueError, match="limit must be"):
        search.search(db, "fire", mode="text", limit=search.MAX_LIMIT + 1)


# --- facets ---


def test_facets_count_spells_not_chunks(db):
    """Fire Bolt is two chunks; counting rows would report every class twice over."""
    found = search.facets(db)
    assert found.chunks == 7
    # Five distinct names, but Armblade is an item and Cover is an SRD section.
    assert found.spells == 4
    assert dict((f.value, f.count) for f in found.classes)["Wizard"] == 3


def test_facets_offer_the_levels_that_exist(db):
    """SRD rows are excluded: they carry level 0 as a placeholder, not as a cantrip."""
    found = search.facets(db)
    assert [(level.level, level.label) for level in found.levels] == [
        (-1, "Not a spell"), (0, "Cantrip"), (1, "Level 1"), (3, "Level 3"),
    ]


def test_facets_report_how_much_of_the_index_is_rulebook(db):
    """The doc-type counts are what let a client offer the filter with real numbers."""
    found = search.facets(db)
    assert dict((f.value, f.count) for f in found.doc_types) == {
        "spell": 4, "item": 1, "srd": 1,
    }


def test_level_labels_are_written_in_one_place():
    assert search.level_label(0) == "Cantrip"
    assert search.level_label(3) == "Level 3"
    assert search.level_label(-1) == "Not a spell"
    assert search.level_label(None) == "Not a spell"

# --- document types ---


def test_the_default_search_is_spells_only(db):
    """``spells_only`` defaults true, so the API's default is the recommender's view.

    The diagnostic surface can widen to the whole collection, but it must not do so by
    accident - a caller who did not ask for the rulebook should not get it.
    """
    names = {hit.name for hit in search.search(db, "", mode="text").hits}
    assert names == {"Fire Bolt", "Fireball", "Cure Wounds", "Detect Magic"}


def test_the_whole_collection_is_reachable_on_request(db):
    """``spells_only=false`` with no doc type is everything the index holds."""
    names = {
        hit.name
        for hit in search.search(db, "", mode="text", spells_only=False).hits
    }
    assert names == {"Fire Bolt", "Fireball", "Cure Wounds", "Detect Magic",
                     "Cover", "Armblade"}


def test_a_doc_type_filter_selects_only_that_kind(db):
    spells_only = search.search(db, "", mode="text", doc_type="spell")
    assert {hit.name for hit in spells_only.hits} == {
        "Fire Bolt", "Fireball", "Cure Wounds", "Detect Magic",
    }
    rules_only = search.search(db, "", mode="text", doc_type="srd")
    assert [hit.name for hit in rules_only.hits] == ["Cover"]
    items_only = search.search(db, "", mode="text", doc_type="item")
    assert [hit.name for hit in items_only.hits] == ["Armblade"]


def test_doc_type_takes_precedence_over_spells_only(db):
    """The two are the same question at different resolutions.

    Honouring both would make ``doc_type=srd`` with the default ``spells_only=true`` match
    nothing at all - a filter that silently returns an empty page.
    """
    result = search.search(db, "", mode="text", doc_type="srd", spells_only=True)
    assert [hit.name for hit in result.hits] == ["Cover"]
    assert result.where == {"doc_type": "srd"}


def test_an_srd_hit_carries_the_heading_it_came_from(db):
    """A rule hit has to be openable, which needs the document and the slug."""
    hit = search.search(db, "", mode="text", doc_type="srd").hits[0]
    assert hit.doc_type == "srd"
    assert hit.document == "playing-the-game"
    assert hit.slug == "cover"


def test_a_rule_and_a_spell_of_the_same_name_are_counted_separately(db):
    """The three kinds of text share a namespace, so the distinct key includes the type.

    The SRD has a ``#### Fireball`` *and* the corpus has a Fireball spell; keying on the
    name alone would fold the rule into the spell and report one fewer row than exists.
    """
    rows = [
        {"spell_name": "Fireball", "doc_type": "spell", "filename": "Fireball.md"},
        {"spell_name": "Fireball", "doc_type": "srd", "filename": "spells"},
    ]
    assert len(search._distinct_spells(rows)) == 2


def test_an_unknown_doc_type_is_rejected(db):
    with pytest.raises(ValueError, match="Unknown doc_type"):
        search.search(db, "fire", mode="vector", doc_type="monster")


def test_a_rule_is_not_reported_as_a_cantrip(db):
    """An SRD row's ``level`` is 0 as a placeholder, and calling that "Cantrip" is a lie.

    A client cannot detect it: the row has no school either, so the two fields that would
    give it away both read as a cantrip's.
    """
    hit = search.search(db, "", mode="text", doc_type="srd").hits[0]
    assert hit.level_label == "Rule"
    assert search.level_label(0) == "Cantrip", "a real cantrip is unaffected"
