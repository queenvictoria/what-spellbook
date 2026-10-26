"""Tests for the spell parsing and eligibility rules in spells.py.

These encode the 2024 Pact of the Tome rules. The corpus header format is
inconsistent (tag order varies, the class list holds spaces before commas, cantrips
use #Cantrip instead of #Level0), so the parser is tested against each real variant
rather than an idealised one.
"""

import pytest

from backend.libs import spells


# --- parsing ---

BESTOW_CURSE = """# [Bestow Curse](https://www.dndbeyond.com/spells/2618923-bestow-curse)

#Level3 #Necromancy ( #Bard, #Cleric, #Wizard)
**Casting Time:** Action
"""

FIREBALL = """# [Fireball](https://www.dndbeyond.com/spells/2618887-fireball)

#Level3 #Evocation ( #Sorcerer, #Wizard)

**Casting Time:** Action
"""

# Real corpus quirk: a space before the comma in the class list.
DARKNESS = """# [Darkness](https://www.dndbeyond.com/spells/2619080-darkness)

#Level2 #Evocation ( #Sorcerer , #Warlock, #Wizard)

**Casting Time:** Action
"""

# Real corpus quirk: cantrips carry #Cantrip and put the school first.
ACID_SPLASH = """# [Acid Splash](https://www.dndbeyond.com/spells/2618844-acid-splash)

 #Evocation #Cantrip ( #Sorcerer, #Wizard)

**Casting Time:** Action
"""

# Real corpus quirk: the Ritual marker lives in the Casting Time value, not a hashtag.
DETECT_MAGIC = """# [Detect Magic](https://www.dndbeyond.com/spells/detect-magic)

#Level1 #Divination ( #Bard, #Cleric, #Druid )

**Casting Time:** Action or Ritual
"""

# A magic item page is mixed into the same directory as the spells.
ARMBLADE = """# [Armblade](https://www.dndbeyond.com/magic-items/215692-armblade)

#Weapon (any one-handed melee weapon), #Common (requires attunement by a warforged)_

An armblade is a magic weapon.
"""


def test_parses_level_school_and_class_list():
    spell = spells.parse_spell("Bestow Curse", "Bestow Curse.md", BESTOW_CURSE)
    assert spell.level == 3
    assert spell.school == "Necromancy"
    assert spell.classes == frozenset({"Bard", "Cleric", "Wizard"})
    assert not spell.is_cantrip
    assert spell.is_spell


def test_cantrip_is_level_zero():
    spell = spells.parse_spell("Acid Splash", "Acid Splash.md", ACID_SPLASH)
    assert spell.level == 0
    assert spell.is_cantrip


def test_tolerates_space_before_comma_in_class_list():
    """The corpus writes '#Sorcerer , #Warlock' in some files."""
    spell = spells.parse_spell("Darkness", "Darkness.md", DARKNESS)
    assert spell.classes == frozenset({"Sorcerer", "Warlock", "Wizard"})


def test_detects_ritual_from_casting_time():
    """There is no #Ritual tag anywhere in the corpus."""
    spell = spells.parse_spell("Detect Magic", "Detect Magic.md", DETECT_MAGIC)
    assert spell.is_ritual


def test_non_ritual_spell_is_not_flagged():
    assert not spells.parse_spell("Fireball", "Fireball.md", FIREBALL).is_ritual


def test_ritual_mention_in_body_does_not_false_positive():
    """A page that only talks about rituals in prose is not a ritual spell."""
    text = FIREBALL + "\nYou can also cast this as a ritual if you have the Ritual tag.\n"
    assert not spells.parse_spell("Fireball", "Fireball.md", text).is_ritual


def test_magic_item_is_not_a_spell():
    spell = spells.parse_spell("Armblade", "Armblade.md", ARMBLADE)
    assert not spell.is_spell
    assert spell.level is None


def test_attunement_parens_do_not_leak_into_classes():
    """'(requires attunement by a warforged)' must not parse as a class list."""
    spell = spells.parse_spell("Armblade", "Armblade.md", ARMBLADE)
    assert spell.classes == frozenset()


def test_unparseable_page_does_not_raise():
    spell = spells.parse_spell("Mystery", "Mystery.md", "no header markers at all")
    assert spell.level is None
    assert spell.classes == frozenset()


def test_body_refactor_does_not_leak_level_into_header():
    """The header block stops at Casting Time so body text cannot alter the level."""
    text = DETECT_MAGIC + "\n**Using a Higher-Level Spell Slot.** At level 4 you learn more.\n"
    assert spells.parse_spell("Detect Magic", "d.md", text).level == 1


# --- name prettification ---


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("Tenser_s Floating Disk", "Tenser's Floating Disk"),
        ("Drawmij_s Instant Summons", "Drawmij's Instant Summons"),
        ("Acid Splash", "Acid Splash"),
        ("Melf-s Acid Arrow", "Melf's Acid Arrow"),
    ],
)
def test_prettify_name_restores_apostrophes(stem, expected):
    assert spells.prettify_name(stem) == expected


# --- metadata round trip ---

def test_metadata_round_trips_through_spell_from_metadata():
    original = spells.parse_spell("Bestow Curse", "Bestow Curse.md", BESTOW_CURSE)
    metadata = spells.build_metadata(original, "data/x/Bestow Curse.md")
    restored = spells.spell_from_metadata(metadata)
    assert restored.level == 3
    assert restored.classes == original.classes
    assert restored.school == original.school
    assert restored.is_ritual == original.is_ritual


def test_metadata_level_is_numeric_for_chroma_comparisons():
    """Chroma can only do $lte on numeric metadata, so level must not be a string."""
    metadata = spells.build_metadata(
        spells.parse_spell("Fireball", "Fireball.md", FIREBALL), "p"
    )
    assert isinstance(metadata["level"], int)


def test_unparseable_level_becomes_sentinel():
    spell = spells.parse_spell("Mystery", "Mystery.md", "nothing")
    assert spells.build_metadata(spell, "p")["level"] == -1


def test_metadata_reads_legacy_tags_string():
    """An index built before numeric metadata must still yield a level."""
    restored = spells.spell_from_metadata({"filename": "Fireball.md", "tags": "Level3, Wizard"})
    assert restored.level == 3


# --- filter construction ---


def test_build_where_returns_none_when_empty():
    assert spells.build_where(None, None) is None


def test_build_where_unwraps_a_single_clause():
    """Chroma rejects $and with one child, so a lone clause must stay bare."""
    assert spells.build_where({"level": 0}) == {"level": 0}


def test_build_where_ands_multiple_clauses():
    assert spells.build_where({"a": 1}, {"b": 2}) == {"$and": [{"a": 1}, {"b": 2}]}


def test_book_cantrip_filter_restricts_to_cantrips():
    where = spells.book_cantrip_filter()
    assert {"is_spell": True} in where["$and"]
    assert {"level": 0} in where["$and"]


def test_book_ritual_filter_requires_level_1_and_ritual():
    where = spells.book_ritual_filter()
    assert {"level": spells.BOOK_RITUAL_MAX_LEVEL} in where["$and"]
    assert {"ritual": True} in where["$and"]


def test_exclude_names_omitted_when_nothing_known():
    where = spells.book_cantrip_filter(exclude_names=[])
    assert not any("spell_name" in clause for clause in where["$and"])


def test_exclude_names_produces_nin_clause():
    where = spells.book_cantrip_filter(exclude_names=["Hex", "Eldritch Blast"])
    assert {"spell_name": {"$nin": ["Hex", "Eldritch Blast"]}} in where["$and"]


# --- eligibility ---

CANTrip = spells.parse_spell("Acid Splash", "acid.md", ACID_SPLASH)
RITUAL = spells.parse_spell("Detect Magic", "detect.md", DETECT_MAGIC)
LEVELLED = spells.parse_spell("Fireball", "fireball.md", FIREBALL)
ITEM = spells.parse_spell("Armblade", "arm.md", ARMBLADE)
POOL = (ITEM, CANTrip, RITUAL, LEVELLED)


def test_eligible_cantrips_returns_only_spells():
    assert spells.eligible_cantrips(POOL) == [CANTrip]


def test_eligible_rituals_returns_only_level_1_rituals():
    assert spells.eligible_rituals(POOL) == [RITUAL]


def test_eligible_rituals_excludes_levelled_rituals():
    """A level 2 ritual cannot go in the book, which takes level 1 rituals only."""
    higher = spells.parse_spell("Silence", "s.md", "#Level2 #Illusion ( #Bard )\n\n**Casting Time:** Action or Ritual\n")
    assert spells.eligible_rituals([RITUAL, higher]) == [RITUAL]


def test_known_spells_are_excluded_from_both_lanes():
    assert spells.eligible_cantrips(POOL, known_spells=["Acid Splash"]) == []
    assert spells.eligible_rituals(POOL, known_spells={"detect magic"}) == []


def test_known_spell_exclusion_is_case_insensitive():
    assert spells.eligible_rituals(POOL, known_spells=["DETECT MAGIC"]) == []


# --- rendering ---


def test_describe_pool_dedupes_repeated_spells():
    """Lanes can each return the same spell; it must appear once."""
    assert spells.describe_pool([CANTrip, CANTrip, RITUAL]).count("Acid Splash") == 1


def test_describe_pool_honours_exclude():
    rendered = spells.describe_pool([CANTrip, RITUAL], exclude=["Acid Splash"])
    assert "Acid Splash" not in rendered
    assert "Detect Magic" in rendered


def test_describe_pool_labels_cantrips_and_rituals():
    rendered = spells.describe_pool([CANTrip, RITUAL])
    assert "Cantrip" in rendered
    assert "Ritual" in rendered


def test_describe_pool_annotates_class_access():
    """The any-class access is the point of the pact, so the pool must show it."""
    assert "Sorcerer" in spells.describe_pool([CANTrip])


def test_describe_pool_empty_is_empty_string():
    assert spells.describe_pool([]) == ""


# --- book pick validation (deterministic guard on model output) ---

POOL_C = [spells.Spell(name=n, filename="c.md", level=0)
          for n in ("Light", "Mending", "Fire Bolt")]
POOL_R = [spells.Spell(name=n, filename="r.md", level=1, is_ritual=True)
          for n in ("Detect Magic", "Alarm")]


def _book(index=1, cantrips=("Light", "Mending", "Fire Bolt"), rituals=("Detect Magic", "Alarm")):
    lines = [f'### Book {index}: "Theme"', "**Cantrips:**"]
    lines += [f"{i}. **{n}** - because." for i, n in enumerate(cantrips, 1)]
    lines.append("**Rituals:**")
    lines += [f"{i}. **{n}** - because." for i, n in enumerate(rituals, 1)]
    lines.append("**How to Use:** prose that mentions Light and no bullets.")
    return "\n".join(lines) + "\n"


def test_validator_accepts_a_clean_answer():
    assert spells.validate_book_picks(_book(), POOL_C, POOL_R) == []


def test_validator_accepts_all_three_books():
    """Per-book splitting matters: picks must not accumulate across books."""
    answer = _book(1) + _book(2) + _book(3)
    assert spells.validate_book_picks(answer, POOL_C, POOL_R) == []


def test_validator_flags_spell_from_rules_context_not_pool():
    """The recurring failure: Guiding Bolt is always-prepared via the patron, so it
    appears in the rules text but is not a legal book pick."""
    answer = _book(cantrips=("Light", "Guiding Bolt", "Fire Bolt"))
    problems = spells.validate_book_picks(answer, POOL_C, POOL_R)
    assert any("Guiding Bolt" in p for p in problems)


def test_validator_flags_already_prepared_spell():
    answer = _book(cantrips=("Light", "Fire Bolt", "Mending"))
    problems = spells.validate_book_picks(answer, POOL_C, POOL_R, known=["Fire Bolt"])
    assert any("already prepared" in p for p in problems)


def test_validator_flags_wrong_pick_count():
    answer = _book(cantrips=("Light",))
    problems = spells.validate_book_picks(answer, POOL_C, POOL_R)
    assert any("expected 3 cantrips" in p for p in problems)


def test_validator_never_demands_more_than_the_pool_holds():
    """A small pool must not be reported as under-filled."""
    answer = _book(cantrips=("Light",), rituals=("Detect Magic",))
    assert spells.validate_book_picks(answer, POOL_C[:1], POOL_R[:1]) == []


def test_validator_reports_the_book_number():
    answer = _book(1) + _book(2, cantrips=("Nope", "Light", "Mending"))
    problems = spells.validate_book_picks(answer, POOL_C, POOL_R)
    assert any(p.startswith("book 2:") for p in problems)


def test_validator_strips_copied_pool_annotations():
    """Models often paste the pool's '(Cantrip; School; Classes)' suffix into the
    bolded name; unmasked, that made every pick look illegal."""
    answer = _book(cantrips=[
        "Light (Cantrip; Evocation; Bard)",
        "Mending (Cantrip; Transmutation; Bard)",
        "Fire Bolt (Cantrip; Evocation; Sorcerer)",
    ])
    assert spells.validate_book_picks(answer, POOL_C, POOL_R) == []


def test_validator_ignores_prose_outside_pick_lists():
    """Naming a prepared spell under 'How to Use' is correct and must not be flagged."""
    answer = _book() + "**Pairing:** Eldritch Blast and Guiding Bolt pair well.\n"
    assert spells.validate_book_picks(answer, POOL_C, POOL_R, known=["Eldritch Blast"]) == []


def test_validator_tolerates_answers_without_book_headings():
    """An unrecognised layout yields no claims rather than false alarms."""
    assert spells.validate_book_picks("Just prose, no structure.", POOL_C, POOL_R) == []


@pytest.mark.parametrize("entry,expected", [
    ("1. **Light** - provides illumination.", "Light"),
    ("- **Detect Magic** for awareness.", "Detect Magic"),
    ("2. Light - plain text entry.", "Light"),
    ("1. **Light (Cantrip; Evocation; Bard/Cleric)**", "Light"),
    ("1. **Detect Magic (Level 1; Divination; Ritual; Wizard)**", "Detect Magic"),
])
def test_entry_name_extraction(entry, expected):
    assert spells._entry_name(entry) == expected


# --- real model output shapes ---
#
# The two shapes below are copied from actual runs. Both previously produced zero
# picks, which meant validation silently reported a clean answer: the guard could not
# see the picks it was meant to check.

def test_validator_reads_inline_comma_separated_picks():
    """The model usually writes '**Cantrips:** A, B, C' on one line, not bullets."""
    answer = (
        "## Book 1 — Bridge Push\n"
        "**Cantrips:** Light, Mending, Fire Bolt\n"
        "**Level 1 rituals:** Detect Magic, Alarm\n"
    )
    assert spells.validate_book_picks(answer, POOL_C, POOL_R) == []


def test_validator_reads_lowercase_ritual_labels():
    """'Level 1 rituals' is as common as 'Level 1 Rituals'."""
    answer = "## Book 1 — A\n**Cantrips:** Light, Mending, Fire Bolt\n"
    assert spells._book_picks(spells._iter_books(answer).__next__())["cantrips"] == [
        "Light", "Mending", "Fire Bolt",
    ]
    answer = "## Book 1 — A\n**level 1 rituals:** Detect Magic, Alarm\n"
    assert spells._book_picks(spells._iter_books(answer).__next__())["rituals"] == [
        "Detect Magic", "Alarm",
    ]


def test_inline_splitting_does_not_tear_annotations_apart():
    """Annotations contain semicolons, so they must be stripped before splitting."""
    picks = spells._split_pick_list(
        "Light (Cantrip; Evocation; Bard), Mending (Cantrip; Transmutation; Bard)"
    )
    assert picks == ["Light", "Mending"]


def test_validator_still_flags_an_illegal_inline_pick():
    answer = (
        "## Book 1 — A\n"
        "**Cantrips:** Guiding Bolt, Mending, Fire Bolt\n"
        "**Rituals:** Detect Magic, Alarm\n"
    )
    problems = spells.validate_book_picks(answer, POOL_C, POOL_R)
    assert any("Guiding Bolt" in p for p in problems)


def test_book_item_annotation_is_not_mistaken_for_a_label():
    """An unanchored label regex matched the 'Cantrip' inside a pick's annotation."""
    answer = "## Book 1 — A\n**Cantrips:**\n1. **Light** (Cantrip; Evocation; Bard) - bright.\n"
    assert spells._book_picks(spells._iter_books(answer).__next__()) == {
        "cantrips": ["Light"], "rituals": [],
    }


def test_validator_accepts_a_typographic_apostrophe():
    """A model writes "Tenser’s Floating Disk"; the corpus uses a straight "'".

    Without normalisation a perfectly legal pick is reported as illegal, and the user
    is warned off a correct answer.
    """
    pool_c = [spells.Spell(name=n, filename="c.md", level=0)
              for n in ("Light", "Mending", "Fire Bolt")]
    pool_r = [spells.Spell(name="Tenser's Floating Disk", filename="t.md", level=1, is_ritual=True)]
    answer = (
        "## Book 1 — A\n"
        "**Cantrips:** Light, Mending, Fire Bolt\n"
        "**Rituals:** Tenser\u2019s Floating Disk\n"
    )
    assert spells.validate_book_picks(answer, pool_c, pool_r) == []


@pytest.mark.parametrize("raw", [
    "Tenser\u2019s Floating Disk", "Tenser\u2018s Floating Disk", "Tenser\u2019s Floating Disk",
])
def test_entry_name_normalises_apostrophes(raw):
    assert spells._entry_name(raw) == "Tenser's Floating Disk"


def test_iter_books_splits_bold_headings():
    """The model often bolds headings instead of using '#': '**Book 1 — Title**'.

    The previous heading splitter only matched '#' headings, so a bold-style answer
    yielded no sections at all and validation passed without examining a single pick.
    """
    answer = (
        "**Book 1 — Radiant Chokepoint**\n"
        "- **Cantrips:** Light, Mending, Fire Bolt\n"
        "- **Level 1 rituals:** Detect Magic, Alarm\n"
        "\n**Book 2 — Anti-Raiser**\n"
        "- **Cantrips:** Message, Mage Hand, Mending\n"
        "- **Rituals:** Alarm, Identify\n"
    )
    sections = list(spells._iter_books(answer))
    assert len(sections) == 2
    assert spells._book_picks(sections[0])["rituals"] == ["Detect Magic", "Alarm"]


def test_validator_reads_bullet_prefixed_labels():
    """'- **Cantrips:** A, B, C' is a label inside a list item, not a bulleted pick."""
    answer = (
        "**Book 1 — A**\n"
        "- **Cantrips:** Light, Mending, Fire Bolt\n"
        "- **Level 1 rituals:** Detect Magic, Alarm\n"
    )
    assert spells.validate_book_picks(answer, POOL_C, POOL_R) == []


def test_iter_books_yields_something_for_every_layout_it_claims_to_support():
    """A silently empty split makes the guard vacuous, so pin the count."""
    for heading in ("## Book 1 — Title", "**Book 1: Title**", "**Book 1 — Title**", "Book 1 - Title"):
        answer = f"{heading}\n**Cantrips:** Light, Mending, Fire Bolt\n"
        assert list(spells._iter_books(answer)), f"no section found for {heading!r}"
