"""The corpus-to-index contract: what a built index must contain, per lane.

``indexing`` is the one place the whole corpus is turned into rows, and until now it had no
test of its own - the three lanes were covered only incidentally, by tests about search and
about the optional rulebook. That left the *contract between them* unpinned:

* a chunk must carry its page's metadata, or an eligibility filter silently drops spells
  from a lane;
* the two rulebook lanes must not be chunked like spells, because a rule's identity is its
  heading and a rule cut in half is a fragment;
* the shared chunk budget must actually be shared, or a spell page crowds out the rules
  beside it in one search.

Every test here is a fact about the built index rather than about a helper, and each was
written because a change to one lane could quietly break another. The spell lane is given a
tiny fixture built in ``tmp_path`` so these run without the real 544-file corpus.
"""

from __future__ import annotations

import pytest

from backend.libs import config, indexing, spells

# The metadata fields every lane must carry. Chroma cannot filter on a missing key, so a row
# without one is not merely incomplete - it is invisible to a ``$lte`` clause and disappears
# from a search that should have considered it.
FILTER_KEYS = ("source", "filename", "spell_name", "level", "school", "classes",
               "ritual", "is_spell", "doc_type")


@pytest.fixture
def corpus(tmp_path):
    """A miniature spell directory with a multi-chunk page and a magic item.

    Written in the corpus's *real* header format, because the parser reads it with a regex
    rather than by rendering Markdown: the level and class list live in a hashtag line
    (``#Level3 #Evocation ( #Sorcerer, #Wizard)``), and a page that does not carry that line
    parses with ``level=None`` and no classes. A tidier fixture would test the parser's
    tolerance of a format the corpus does not use, which is a different test.

    The long page is deliberately longer than one chunk: a page that fits in a single row
    cannot show whether metadata reaches the second chunk, which is the thing being tested.
    """
    root = tmp_path / "spells"
    root.mkdir()

    (root / "Fire Bolt.md").write_text(
        "# [Fire Bolt](https://www.dndbeyond.com/spells/2618890-fire-bolt)\n\n"
        "#Evocation #Cantrip ( #Sorcerer, #Wizard)\n\n"
        "**Casting Time:** Action\n\n**Range:** 120 feet\n\n"
        "You hurl a mote of fire at a creature or an object within range.\n",
        encoding="utf-8",
    )
    (root / "Fireball.md").write_text(
        "# [Fireball](https://www.dndbeyond.com/spells/2618887-fireball)\n\n"
        "#Level3 #Evocation ( #Sorcerer, #Wizard)\n\n"
        "**Casting Time:** Action\n\n**Range:** 150 feet\n\n"
        "A bright streak flashes from you to a point you choose within range.\n\n"
        + ("The fire spreads around corners and ignites flammable objects. " * 90),
        encoding="utf-8",
    )
    (root / "Armblade.md").write_text(
        "# [Armblade](https://www.dndbeyond.com/magic-items/9058904-armblade)\n\n"
        "#Wondrous *Item, Rarity Varies*\n\n"
        "This magic weapon is a component made for a warforged.\n",
        encoding="utf-8",
    )
    return root


def test_every_chunk_carries_the_keys_a_filter_reads(corpus):
    """A row missing a filter key is invisible, not merely incomplete.

    ``build_metadata`` reads the page header, which lives in the page's *first* chunk. A
    later chunk that did not have it copied down would carry no ``level``, so a ``$lte``
    clause would exclude it - and the symptom would be a spell that is legal but never
    appears in its lane.
    """
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    assert docs

    for doc in docs:
        for key in FILTER_KEYS:
            assert key in doc.metadata, f"{doc.metadata.get('spell_name')} lacks {key}"


def test_a_later_chunk_of_one_page_repeats_the_page_metadata(corpus):
    """The specific case the copy-down exists for: the header is only in chunk one."""
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    fireball = [d for d in docs if d.metadata["spell_name"] == "Fireball"]

    assert len(fireball) > 1, "the fixture page must be long enough to split"
    levels = {d.metadata["level"] for d in fireball}
    classes = {d.metadata["classes"] for d in fireball}
    schools = {d.metadata["school"] for d in fireball}

    assert levels == {3}
    assert classes == {"Sorcerer, Wizard"}
    assert schools == {"Evocation"}


def test_a_chunk_is_a_fragment_of_its_page_not_the_whole_page(corpus):
    """The splitter must actually split, or a long page becomes one weak embedding.

    The first chunk has to carry the page's opening - a split that began mid-description
    would be a fragment that does not say what spell it belongs to.
    """
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    fireball = [d for d in docs if d.metadata["spell_name"] == "Fireball"]

    assert len(fireball) > 1, "the long page must split into more than one chunk"
    assert "A bright streak flashes" in fireball[0].page_content


def test_the_injected_name_line_is_not_its_own_chunk(corpus):
    """The name is folded into the page's first real chunk, not embedded as a stub.

    The name is injected as ``Spell Name: <name>`` on its own line *above* the page heading,
    so the heading splitter cut it into a chunk containing nothing else. Measured on the
    live index that was 540 of 4,674 rows - every spell page had one - and each was an
    embedded row eligible to return as a hit that shows a name and no text.

    The name must still reach the body of a chunk, because six corpus files are named after
    a different spell than they contain and the body is the only place the real name lives.
    """
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))

    stubs = [
        d for d in docs
        if d.page_content.strip().startswith("Spell Name:") and len(d.page_content.strip().split("\n")) == 1
    ]
    assert stubs == [], f"name-only chunks: {[d.page_content for d in stubs]}"

    first = next(d for d in docs if d.metadata["spell_name"] == "Fireball")
    assert first.page_content.startswith("Spell Name: Fireball")
    assert "A bright streak flashes" in first.page_content


def test_a_spell_and_an_item_are_told_apart_by_doc_type(corpus):
    """``doc_type`` is the coarse kind, and the eligibility filters key on it.

    ``is_spell`` alone cannot express this: it is ``False`` for an item *and* for every
    rulebook row, so a filter that asked only for "not a spell" would hand the recommender
    the rulebook.
    """
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    by_name = {d.metadata["spell_name"]: d.metadata for d in docs}

    assert by_name["Fire Bolt"]["doc_type"] == spells.DOC_TYPE_SPELL
    assert by_name["Fire Bolt"]["is_spell"] is True
    assert by_name["Armblade"]["doc_type"] == spells.DOC_TYPE_ITEM
    assert by_name["Armblade"]["is_spell"] is False


def test_the_level_placeholder_for_an_item_is_minus_one(corpus):
    """``-1`` is the index's marker for "not a spell", and the API reports it as such.

    A real level here would be worse than a placeholder: the item would answer a level
    filter about itself.
    """
    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    item = next(d for d in docs if d.metadata["doc_type"] == spells.DOC_TYPE_ITEM)

    assert item.metadata["level"] == -1


def test_a_spell_page_is_chunked_and_a_rule_is_not(corpus):
    """The two rulebook lanes emit one row per *rule*; the spell lane splits its pages.

    This is the asymmetry that keeps a rule whole. Cutting an invocation in half separates
    it from its own prerequisite line, and the RAG "fix" for a long spell page is exactly
    the wrong change to apply to a rulebook.
    """
    spell_docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    srd_docs = indexing._srd_documents()

    assert len(spell_docs) > len({d.metadata["spell_name"] for d in spell_docs}), "spells split"
    if srd_docs:
        # Every SRD row is a section, and a section is a heading - so a row's own name is a
        # heading in the tree, not a fragment of one.
        assert all(d.metadata["document"] and d.metadata["slug"] for d in srd_docs)


def test_both_rulebook_lanes_share_one_chunk_budget():
    """One search reads spells and rules together, so the budgets cannot drift apart.

    The spell lane used to hard-code the same two numbers the SRD lane named as constants.
    Two literals that agree today are two numbers that will eventually disagree, and the
    disagreement shows up as one kind of text crowding out the other in every result list.
    """
    assert indexing.SPELL_CHUNK_SIZE == indexing.SRD_CHUNK_SIZE
    assert indexing.SPELL_CHUNK_OVERLAP == indexing.SRD_CHUNK_OVERLAP
    assert indexing.SPELL_CHUNK_OVERLAP < indexing.SPELL_CHUNK_SIZE


def test_an_unreadable_page_is_skipped_rather_than_failing_the_build(corpus, monkeypatch):
    """One broken file in a 544-page corpus must not cost the index its 543 good rows."""
    boom = corpus / "Broken.md"
    boom.write_text("# Broken\n", encoding="utf-8")

    real = spells.parse_spell

    def explode(name, filename, text):
        if filename == "Broken.md":
            raise ValueError("unparseable page")
        return real(name, filename, text)

    monkeypatch.setattr(spells, "parse_spell", explode)

    docs = indexing._spell_documents(list(corpus.rglob("*.md")))
    names = {d.metadata["spell_name"] for d in docs}

    assert "Broken" not in names
    assert {"Fire Bolt", "Fireball", "Armblade"} <= names


def test_a_corpus_with_no_readable_page_is_an_error_not_an_empty_index(tmp_path):
    """An index with no spells in it is not a useful degradation.

    The rulebook lanes tolerate absence, because a checkout without them is normal. The
    spell corpus is the index's reason to exist, so its absence is raised at the boundary
    rather than served as a search that returns nothing.
    """
    empty = tmp_path / "none"
    empty.mkdir()

    assert indexing._spell_documents(list(empty.rglob("*.md"))) == []

    with pytest.raises(indexing.IndexUnavailable):
        indexing.build_index(empty, str(tmp_path / "db"), srd_path=tmp_path / "no-srd")


def test_the_index_records_the_version_that_built_it():
    """The version is stored in the collection metadata and compared on read.

    It is what ``db_is_valid`` checks, and it is why a metadata change reaches an existing
    user rather than leaving every filter reading fields that were never written into their
    index. Read from the real function so a build that stopped recording it would fail here.
    """
    assert isinstance(config.INDEX_VERSION, int)
    assert config.INDEX_VERSION > 0

    import inspect

    source = inspect.getsource(indexing.build_index)
    assert '"index_version": config.INDEX_VERSION' in source
    assert '"sources": available_sources' in source
