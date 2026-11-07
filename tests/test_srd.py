"""Browsing the vendored SRD: the tree, the anchors, and the table conversion.

These run against the real corpus rather than a fixture. The tree is derived from the
files' own headings, so a fake corpus would assert whatever a one-line file implies and
prove nothing about the 1280 headings that actually exist - the same trap that made a
stubbed SRD useless for testing the rules matcher.
"""

from __future__ import annotations

import pytest

from backend.libs import rules, srd


def test_every_vendored_file_is_a_document():
    """The tree covers the corpus, and only the corpus.

    ``PROVENANCE.md`` is excluded by ``rules.source_files``: it is the CC-BY-4.0
    attribution, not SRD text.
    """
    names = [document.name for document in srd.documents()]
    assert names == ["rules-glossary", "playing-the-game", "gameplay-toolbox",
                     "equipment", "classes", "spells"]
    assert "PROVENANCE" not in names


def test_a_document_is_titled_by_its_own_h1():
    """The file's title is the file's, not a prettified filename."""
    assert srd.document("classes").title == "Classes"
    assert srd.document("rules-glossary").title == "Rules Glossary"


def test_the_bom_does_not_swallow_the_first_heading():
    """``spells.md`` begins with a BOM, and left in place it defeats the heading regex.

    The symptom is quiet and wrong: the file's title falls back to "Spells" by luck, but
    its top-level sections become siblings of nothing instead of children of the title.
    """
    spells = srd.document("spells")
    assert len(spells.headings) == 1
    assert spells.headings[0].text == "Spells"
    assert len(spells.headings[0].children) == 12


def test_headings_nest_by_level_even_when_levels_skip():
    """``spells.md`` goes from ``##`` straight to ``####`` for 352 spells.

    A parser that required an intervening ``###`` would drop every spell description.
    """
    spells = srd.document("spells")
    descriptions = next(
        heading for heading in spells.headings[0].children
        if heading.text == "Spell Descriptions"
    )
    assert len(descriptions.children) == 352
    assert all(child.level == 4 for child in descriptions.children)
    assert any(child.text == "Fireball" for child in descriptions.children)


def test_slugs_are_unique_within_every_document():
    """The SRD repeats headings, so a slug from the text alone would collide.

    ``classes.md`` has six ``Level 1: Spellcasting`` sections, one per class, and
    ``playing-the-game.md`` repeats ``Ability Checks``. Without de-duplication every link
    after the first would open the wrong section.
    """
    def walk(headings):
        for heading in headings:
            yield heading.slug
            yield from walk(heading.children)

    for document in srd.documents():
        found = list(walk(document.headings))
        assert len(found) == len(set(found)), document.name


def test_a_repeated_heading_gets_a_numbered_slug():
    """The second ``Level 1: Spellcasting`` is addressable, and is not the first."""
    classes = srd.document("classes")
    slugs = []

    def walk(headings):
        for heading in headings:
            if heading.text == "Level 1: Spellcasting":
                slugs.append(heading.slug)
            walk(heading.children)

    walk(classes.headings)
    assert len(slugs) > 1
    assert slugs[0] == "level-1-spellcasting"
    assert slugs[1] == "level-1-spellcasting-2"


def test_a_heading_inside_a_blockquote_is_not_a_section():
    """``> ### Breaking Your Oath`` is quoted text inside a rule, not a section.

    Giving it an anchor would put a Paladin's oath discussion in the table of contents as a
    sibling of the Paladin class.
    """
    classes = srd.document("classes")

    def walk(headings):
        for heading in headings:
            yield heading.text
            yield from walk(heading.children)

    assert "Breaking Your Oath" not in set(walk(classes.headings))


def test_a_section_is_its_own_text_and_stops_at_the_next_peer():
    section = srd.section("equipment", "coins")
    assert section.heading.text == "Coins"
    assert "Copper Piece (CP)" in section.text
    assert "Weapons" not in section.text


def test_a_section_includes_its_own_heading_line():
    """So the fragment reads as a document rather than a body with no title."""
    assert srd.section("equipment", "coins").text.startswith("## Coins")


def test_a_section_keeps_its_subsections():
    """A parent section owns its children's text, because that is what a reader expects."""
    section = srd.section("equipment", "tools")
    assert "Tool Proficiency" in section.text
    assert "Artisan's Tools" in section.text


def test_tables_become_pipe_tables():
    """The numbers in a table *are* the rule.

    ``### Cover``'s prose only says "as detailed in the Cover table", so a conversion that
    dropped the table would leave a confident rule with its bonuses missing.
    """
    text = srd.section("playing-the-game", "cover").text
    assert "| Degree | Benefit to Target |" in text
    assert "| Half | +2 bonus to AC and Dexterity saving throws |" in text
    assert "<table>" not in text


def test_a_table_without_a_header_gets_an_empty_header_row():
    """Markdown requires a header, and promoting the first row would mislabel the data.

    The SRD's headerless tables are key/value blocks - "Primary Ability | Strength" - where
    the first row is data, not a column name.
    """
    text = srd.section("classes", "barbarian").text
    assert "|  |  |" in text
    assert "| Primary Ability | Strength |" in text


def test_a_multi_row_header_is_merged_column_wise():
    """The class progression tables have two header rows.

    The second holds the spell-slot levels under a ``colspan="9"`` group label. Taking only
    one row would lose either the label or the levels.
    """
    text = srd.section("classes", "bard").text
    assert "——Spell Slots per Spell Level—— 1" in text


def test_colspan_becomes_empty_neighbour_cells():
    """Markdown has no colspan, so a span is widened to keep every row the same width."""
    text = srd.section("equipment", "weapons").text
    # The group label row spans all six columns; the label stays in the first.
    assert "*Simple Melee Weapons*" in text


def test_an_unknown_document_raises_rules_unavailable():
    """A typed error, so the API maps it to a 404 through the same path as a missing rule."""
    with pytest.raises(rules.RulesUnavailable) as caught:
        srd.document("nope")
    assert "equipment" in str(caught.value)


def test_an_unknown_section_raises_rules_unavailable():
    with pytest.raises(rules.RulesUnavailable):
        srd.section("equipment", "nope")


def test_the_whole_document_is_renderable_markdown():
    text = srd.text("equipment")
    assert text.startswith("# Equipment")
    assert "<table>" not in text
    assert "## Coins" in text


def test_the_cache_can_be_cleared():
    """The corpus is editable, so a stale tree must be droppable without a restart."""
    first = srd.documents()
    assert srd.documents() is first
    srd.clear_cache()
    assert srd.documents() is not first


def test_a_stat_block_does_not_swallow_the_spells_after_it():
    """Three spells carry a creature stat block, and the conversion mis-levelled its name.

    ``## Otherworldly Steed`` closes ``## Spell Descriptions``, so left alone the 121 spells
    after *Find Steed* - Fireball among them - become children of a steed's stat block, and
    the same happens again at *Giant Insect* and *Draconic Spirit*. The tree still *looks*
    plausible, which is why this needs a test rather than a glance.
    """
    spells = srd.document("spells")
    descriptions = next(
        heading for heading in spells.headings[0].children
        if heading.text == "Spell Descriptions"
    )
    assert len(descriptions.children) == 352
    names = {child.text for child in descriptions.children}
    assert {"Fireball", "Giant Insect", "Find Steed", "Summon Dragon"} <= names


def test_a_stat_block_sits_at_the_spell_level_not_above_it():
    """The repair moves the stat block down to the spells' own level.

    It cannot make the stat block a *child* of its spell, because the source's own
    ``#### Traits`` is at the spell level too - so the stat block becomes a sibling of the
    spell it belongs to. That is the source's inconsistency, and a sibling is harmless where
    a parent was not: the spells after it stay in ``Spell Descriptions``.
    """
    spells = srd.document("spells")
    descriptions = next(
        heading for heading in spells.headings[0].children
        if heading.text == "Spell Descriptions"
    )
    steed = next(child for child in descriptions.children if child.text == "Otherworldly Steed")
    assert steed.level == 4


# --- anchors, for turning a path into a link -----------------------------------


def test_anchor_finds_a_heading_by_its_text():
    """A caller has a name, not a slug - a spell's `url` is built from its own name."""
    assert srd.anchor("spells", "Fireball") == "fireball"
    assert srd.anchor("equipment", "Coins") == "coins"


def test_anchor_is_case_insensitive():
    """The corpus and the caller disagree about capitalisation, not about the name."""
    assert srd.anchor("spells", "fireball") == "fireball"
    assert srd.anchor("spells", "FIREBALL") == "fireball"


def test_anchor_finds_a_nested_heading():
    """Most rules are four levels deep, so a top-level-only search would find almost none."""
    assert srd.anchor("classes", "Agonizing Blast") == "agonizing-blast"
    assert srd.anchor("playing-the-game", "Difficult Terrain") == "difficult-terrain"


def test_anchor_returns_none_for_a_heading_that_is_not_there():
    """None rather than a guess, so the caller can fall back to the bare file."""
    assert srd.anchor("spells", "Flaming Death Ray") is None
    assert srd.anchor("spells", "") is None


def test_anchor_returns_none_for_an_unknown_document():
    """A missing file is not an error here: the caller only wanted a nicer link."""
    assert srd.anchor("nope", "Fireball") is None


def test_anchor_prefers_the_first_match():
    """The SRD repeats a name for a stat block, and the spell comes first.

    ``#### Giant Insect`` is the spell; ``## Giant Insect`` is its stat block. The spell is
    what a reader following the name wants.
    """
    assert srd.anchor("spells", "Giant Insect") == "giant-insect"


# --- ancestry, for the breadcrumb ---


def test_a_section_knows_the_headings_above_it():
    """A rule read from a citation arrives without its context.

    "Prone [Condition]" does not say it lives under *Rules Definitions* in the *Rules
    Glossary*, and the trail is the only thing that does.
    """
    section = srd.section("rules-glossary", "prone-condition")
    assert [h.text for h in section.ancestors] == ["Rules Glossary", "Rules Definitions"]


def test_the_ancestry_excludes_the_section_itself():
    """The card already titles the section, so repeating it as the last crumb says it twice."""
    section = srd.section("equipment", "coins")
    assert section.heading.text == "Coins"
    assert "Coins" not in [h.text for h in section.ancestors]


def test_the_ancestry_is_ordered_outermost_first():
    """A breadcrumb reads left to right, so the order is part of the contract."""
    section = srd.section("playing-the-game", "cover")
    assert [h.text for h in section.ancestors] == ["Playing the Game", "Combat"]


def test_a_top_level_section_has_only_the_document_root_above_it():
    section = srd.section("classes", "barbarian")
    assert [h.text for h in section.ancestors] == ["Classes"]


def test_the_document_root_has_no_ancestors():
    """The root is the top of the tree, so there is nothing above it to link to."""
    assert srd.section("rules-glossary", "rules-glossary").ancestors == ()


def test_every_ancestor_carries_the_slug_a_link_needs():
    """A crumb is a link to the parent rule, not just a label."""
    section = srd.section("rules-glossary", "prone-condition")
    assert [h.slug for h in section.ancestors] == ["rules-glossary", "rules-definitions"]
    # And each one resolves, so a crumb cannot point at a heading that is not there.
    for heading in section.ancestors:
        assert srd.section("rules-glossary", heading.slug).heading.slug == heading.slug


# --- enumerating every section, for the vector index ---


def test_sections_covers_every_heading_except_the_title_wrapper():
    """The index needs the whole rulebook in one list, and the H1 is not a section.

    ``# Classes`` is immediately followed by ``## Barbarian`` and holds no text of its own,
    so indexing it would add one row containing the entire 298KB chapter.
    """
    found = srd.sections()
    headings = sum(1 for document in srd.documents() for _ in _walk(document.headings))
    assert len(found) == headings - len(srd.documents())
    assert all(heading.level > 1 for _, heading, _ in found)


def _walk(headings):
    for heading in headings:
        yield heading
        yield from _walk(heading.children)


def test_a_section_carries_its_own_text_and_not_its_children():
    """A parent's body stops at the next heading, so a rule is not its whole chapter."""
    found = {(document.name, heading.slug): body for document, heading, body in srd.sections()}
    cover = found[("rules-glossary", "cover")]
    assert "Half Cover" in cover
    # The next glossary entry is a sibling, not part of Cover.
    assert "Crawling" not in cover


def test_a_section_with_no_body_is_still_enumerated():
    """``## Spell Descriptions`` holds only children, and dropping it loses the chapter."""
    found = {(document.name, heading.slug): body for document, heading, body in srd.sections()}
    assert ("spells", "spell-descriptions") in found


def test_sections_agree_with_section_on_the_text():
    """Two readings of the same heading must not disagree about where it ends.

    ``sections`` slices all 1279 headings in one pass and ``section`` slices one on demand;
    if they drifted, a search hit would open a different rule than the one it matched.
    """
    found = {(document.name, heading.slug): body for document, heading, body in srd.sections()}
    for name, slug in (("rules-glossary", "cover"), ("playing-the-game", "combat"),
                       ("spells", "fireball")):
        assert found[(name, slug)].strip() == srd.section(name, slug).text.strip()


def test_tables_survive_into_the_indexed_text():
    """The numbers in a table *are* the rule, so a chunk must carry them.

    ``### Cover``'s prose only says "as detailed in the Cover table"; the +2 and +5 bonuses
    live in the markup. A converter that dropped tables would index a confident rule with
    its numbers missing.
    """
    found = {(document.name, heading.slug): body for document, heading, body in srd.sections()}
    assert "+2" in found[("rules-glossary", "cover")]
