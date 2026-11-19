"""The optional second rulebook: parsing, OCR repair, indexing and absence tolerance.

Two things are being tested here and only one of them is the parser. The other is the
*optionality*, which is the source's whole contract: a machine without the folder must
behave exactly as it did before the source existed, and no test may depend on a checkout
having it. So the tests that need real content run against the installed source and skip
when it is absent, and the ones that must always run build their own tiny fixture.
"""

from __future__ import annotations

import json

import pytest

from backend.libs import config, indexing, ionas, search, spells

# The real source is a third-party checkout that most machines will not have. Anything
# asserting on its content is skipped rather than failed - that is the contract, not a
# concession.
requires_source = pytest.mark.skipif(
    not ionas.available(), reason="the optional rulebook source is not installed"
)


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A miniature rulebook with every file shape the parser dispatches on.

    Built here rather than read from the real checkout so these tests run everywhere, and so
    a shape can be asserted exactly - the real files are 3.6MB and change under us.
    """
    root = tmp_path / "rulebook"
    (root / "classes" / "classChoices").mkdir(parents=True)
    (root / "feats").mkdir()
    (root / "items").mkdir()
    (root / "races").mkdir()
    (root / "rules").mkdir()
    (root / "spells").mkdir()

    (root / "classes" / "warlock.json").write_text(json.dumps({
        "class": "Warlock",
        "spellcasting": {
            "1": {"cantrips": 2, "preparedSpells": 2, "slots": [1, 0, 0, 0, 0, 0, 0, 0, 0]},
            "5": {"cantrips": 3, "preparedSpells": 6, "slots": [0, 0, 2, 0, 0, 0, 0, 0, 0]},
        },
        "features": {
            # The same feature at two levels, as the real source repeats it. It must come
            # out once, with both levels recorded.
            "1": [{"name": "Pact Magic", "description": "Slots return on a Short Rest."}],
            "5": [{"name": "Pact Magic", "description": "Slots return on a Short Rest."}],
            "2": [{"name": "Magical Cunning", "description": "A one m inute rite."}],
            # The declaration that links a class choice to the feature granting it. Real
            # shape: the choice's own file says only "Invocation", so the class and the
            # feature only meet here and in the router below.
            "3": [{"name": "Eldritch Invocations",
                    "description": "You learn fragments of forbidden knowledge.",
                    "classChoices": ["eldritch-invocations"]}],
        },
    }))
    (root / "classes" / "warlock-subclasses.json").write_text(json.dumps({
        "Celestial Patron": {
            "3": [{"name": "Healing Light", "description": "You gain a pool of d6s."}],
        },
    }))
    (root / "classes" / "classChoices" / "agonizing-blast.json").write_text(json.dumps({
        "name": "Agonizing Blast",
        "description": "Add your Charisma modifier.",
        "badge": "Invocation",
    }))
    # A router: a slug -> name map with no text at all. It must contribute nothing.
    (root / "classes" / "classChoices" / "eldritch-invocations.json").write_text(
        json.dumps({"agonizing-blast": "Agonizing Blast (Level 2+ Warlock)"})
    )
    (root / "feats" / "alert.json").write_text(json.dumps({
        "name": "Alert", "description": "You gain a bonus to Initiative.",
    }))
    (root / "items" / "battleaxe.json").write_text(json.dumps({
        "name": "Battleaxe", "type": "martial-weapon", "damage": "1d8 Slashing",
        "cost": 10, "weight": 4, "description": "A heavy blade.",
    }))
    (root / "races" / "aasimar.json").write_text(json.dumps({
        "traits": [{"name": "Darkvision", "description": "You can see in the dark."}],
    }))
    (root / "rules" / "desperate-measures.json").write_text(json.dumps({
        "name": "Desperate Measures",
        "rules": [{"name": "One Death Save", "description": "Dash as an extra action.",
                   "badge": "Critical Role"}],
    }))
    (root / "spells" / "acid-splash.json").write_text(json.dumps({
        "name": "Acid Splash", "level": 0, "school": "Evocation", "castingTime": "Action",
        "range": "60 feet", "components": ["V", "S"], "duration": "Instantaneous",
        "ritual": False, "concentration": False, "classes": "Sorcerer, Wizard",
        "description": "A bubble of acid.",
    }))
    # A per-class spell *list*, not a spell. Its keys are levels, so it must not be read
    # as a spell with a missing name.
    (root / "spells" / "warlock-spells.json").write_text(json.dumps({
        "0": {"eldritch-blast": "Eldritch Blast"},
    }))
    # A previous edition's rulebook, which this 2024-only project must not read.
    old = root / "#past-versions" / "5e"
    old.mkdir(parents=True)
    (old / "warlock.json").write_text(json.dumps({
        "class": "Warlock",
        "features": {"1": [{"name": "Otherworldly Patron", "description": "2014 text."}]},
    }))

    ionas.clear_cache()
    monkeypatch.setattr(config, "IONAS_DIR", str(root))
    yield root
    ionas.clear_cache()


# --- presence is optional -----------------------------------------------------


def test_the_source_is_absent_without_complaint(tmp_path):
    """The whole contract in one test: no directory, no result, no error.

    This is the behaviour every other part of the app depends on. A machine without the
    checkout must behave exactly as it did before this source existed.
    """
    missing = tmp_path / "not-here"
    assert ionas.available(missing) is False
    assert ionas.sections(missing) == []
    assert ionas.files(missing) == []
    assert ionas.names(missing) == []
    assert ionas.lookup("Healing Light", missing) is None
    # And the index lane contributes nothing rather than raising.
    assert indexing._ionas_documents(missing) == []


def test_installing_the_source_changes_which_index_is_current():
    """``INDEX_VERSION`` guards the metadata *shape*; this guards the rows.

    Installing the folder does not change any metadata field, so no version bump can see
    it - and without this check every query would keep reading an index that has none of
    the new rules, with "the search returns too little" as the only symptom.
    """
    assert indexing.available_sources() == indexing.SOURCES_WITH_IONAS
    absent = indexing.available_sources("/tmp/not-installed")
    assert absent == indexing.SOURCES_WITHOUT_IONAS
    assert indexing.available_sources() != absent


def test_an_index_written_before_this_field_existed_is_not_rebuilt(tmp_path, monkeypatch):
    """The regression that would cost every existing user a full re-embed for nothing.

    An index has no ``sources`` key before this change, and a naive ``==`` comparison would
    read that as "stale" for *every* user - including the ones who never install the
    optional source and whose index is therefore already correct.
    """
    monkeypatch.setattr(indexing, "index_metadata", lambda db_dir=None: {
        "index_version": config.INDEX_VERSION,
    })
    missing = tmp_path / "not-installed"
    assert indexing.sources_match(ionas_path=missing) is True


# --- shapes -------------------------------------------------------------------


def test_a_class_feature_is_emitted_once_however_many_levels_it_repeats_at(source):
    """The source lists ``Pact Magic`` at every level it scales at, with identical text.

    Emitting twenty copies would fill the rulebook with duplicates and give one search
    twenty equal hits for one rule.
    """
    found = [s for s in ionas.sections() if s.name == "Pact Magic"]
    assert len(found) == 1
    assert found[0].levels == (1, 5)


def test_a_subclass_feature_is_attributed_to_its_subclass(source):
    """ "Healing Light" alone does not say Celestial Patron, and it is not in the SRD."""
    found = ionas.lookup("Healing Light")
    assert found is not None
    assert found["title"] == "Celestial Patron - Healing Light"
    assert found["text"].startswith("### Healing Light")
    assert found["source"] == "ionas-politis"


def test_the_spellcasting_progression_is_rendered_as_a_table(source):
    """The numbers are the rule, so they are written as a table rather than dropped.

    A Warlock's slots are all one level, which the source encodes as a count at the index
    of that level - reading it as a spread of levels would be the exact rules error this
    project's context files exist to prevent.
    """
    table = next(s for s in ionas.sections()
                 if s.name == "Spellcasting progression" and "Warlock" in s.title)
    assert "| Level |" in table.text
    assert "| 1 | 2 | 2 | 1 | 1 |" in table.text
    assert "| 5 | 3 | 6 | 2 | 3 |" in table.text


def test_a_router_file_contributes_no_rule(source):
    """``eldritch-invocations.json`` is a slug -> name map, and the real one is 28 entries.

    Reading it as content would put 28 bare invocation names in the rulebook with nothing
    under them, which reads as a broken section.
    """
    names = ionas.names()
    assert "Agonizing Blast (Level 2+ Warlock)" not in names
    # The real option file *is* content, and must still be read.
    assert "Agonizing Blast" in names


def test_a_per_class_spell_list_is_not_read_as_a_spell(source):
    """``warlock-spells.json`` is keyed by level; treating it as a spell yields a nameless
    row whose text is a dictionary of other spells."""
    assert "Eldritch Blast" not in ionas.names()


def test_every_kind_of_file_is_dispatched(source):
    """One section from each directory, so a new kind is added deliberately."""
    kinds = {s.kind for s in ionas.sections()}
    assert {"class feature", "subclass feature", "invocation", "feat", "item",
            "species trait", "critical role", "spell", "class"} <= kinds


def test_a_previous_edition_is_never_read(source):
    """``#past-versions`` holds the 2014 rulebook, and this project is 2024-only.

    A mixed corpus is worse than either edition alone, because nothing in the text says
    which one it came from.
    """
    assert "Otherworldly Patron" not in ionas.names()


def test_an_item_keeps_its_mechanical_fields(source):
    """A battleaxe's damage *is* its rule, so it is folded into the text, not dropped."""
    found = ionas.lookup("Battleaxe")
    assert found is not None
    assert "1d8 Slashing" in found["text"]
    assert "Type: martial-weapon" in found["text"]


# --- OCR repair ---------------------------------------------------------------


def test_a_word_broken_by_a_hyphen_is_rejoined(source):
    """The scan wraps words and the wrap survives as a hyphen, which must not become a
    space: ``protec-tion`` is one word."""
    assert "minute" in ionas.lookup("Magical Cunning")["text"]
    assert "m inute" not in ionas.lookup("Magical Cunning")["text"]


def test_a_hyphenated_compound_is_left_alone():
    """The negative case, and the reason the repair is a table rather than a rule.

    ``Cube-shaped``, ``ability-score`` and every slug in the source are hyphenated words,
    so a rule that joined any ``word-word`` would rewrite the source's own file names.
    """
    assert ionas.normalise("a Cube-shaped area and an ability-score increase") == (
        "a Cube-shaped area and an ability-score increase"
    )


def test_ordinary_prose_is_not_glued_together():
    """The other negative case: "a Long Rest" joins to "along", and must not.

    A rule that joined any short fragment to the next word would silently rewrite ordinary
    English, which is why the ambiguous fragments are listed by hand.
    """
    assert ionas.normalise("you finish a Long Rest") == "you finish a Long Rest"
    assert ionas.normalise("creatures you can see in that area") == (
        "creatures you can see in that area"
    )


def test_a_stray_letter_o_becomes_a_zero():
    """ "reduce an enemy to O Hit Points" - the scan's letter O for a zero."""
    assert ionas.normalise("you drop to O Hit Points") == "you drop to 0 Hit Points"
    # The letter O in ordinary prose is untouched.
    assert ionas.normalise("O Patron, hear me") == "O Patron, hear me"


def test_an_embedded_heading_is_not_stated_twice():
    """The source embeds ``#### Fiend Spells`` inside the Fiend Spells prose, and the
    strip would otherwise leave the name as a plain line under its own title."""
    fixed = ionas.normalise("The magic of your patron ensures you have spells ready."
                            "\n#### Fiend Spells\n| A | B |")
    assert "####" not in fixed
    assert "Fiend Spells\n| A | B |" in fixed


def test_repair_is_idempotent():
    """A heading is normalised for display and the body before they are joined, so a
    second pass must not change anything."""
    once = ionas.normalise("m inutes of crea-tures w ith a ward")
    assert ionas.normalise(once) == once


def test_an_unfilled_template_is_not_offered_as_a_rule(tmp_path, monkeypatch):
    """Two feats ship as ``<Feat_Name>`` / ``<Feat_Description>``.

    That is a placeholder, not a rule, and offering it would put a fill-in-the-blank in the
    rulebook.
    """
    root = tmp_path / "r"
    (root / "feats").mkdir(parents=True)
    (root / "feats" / "x.json").write_text(json.dumps(
        {"name": "<Feat_Name>", "description": "<Feat_Description>"}
    ))
    monkeypatch.setattr(config, "IONAS_DIR", str(root))
    ionas.clear_cache()
    try:
        assert ionas.sections() == []
    finally:
        ionas.clear_cache()


# --- indexing -----------------------------------------------------------------


def test_index_rows_carry_the_keys_the_filters_read(source):
    """Chroma cannot filter on a missing key, so a row must carry every field the spell
    filters read - the same requirement the SRD rows have."""
    doc = indexing._ionas_documents()[0]
    for key in ("source", "filename", "spell_name", "level", "school", "classes",
                "ritual", "is_spell", "doc_type", "document", "slug"):
        assert key in doc.metadata, key


def test_index_rows_are_tagged_as_their_own_source(source):
    """The tag is the whole point: a reader must be able to tell this text from the SRD's."""
    docs = indexing._ionas_documents()
    assert docs
    assert all(d.metadata["doc_type"] == spells.DOC_TYPE_IONAS for d in docs)
    assert spells.DOC_TYPE_IONAS != spells.DOC_TYPE_SRD


def test_a_rule_is_not_split_across_chunks(source):
    """One rule, one row. Cutting an invocation in half would separate it from its own
    prerequisite line."""
    docs = indexing._ionas_documents()
    assert len(docs) == len(ionas.sections())


def test_a_rule_is_not_reported_as_a_cantrip(source):
    """``level`` is 0 as a placeholder, exactly as an SRD row uses it."""
    docs = indexing._ionas_documents()
    assert all(d.metadata["level"] == 0 for d in docs)
    assert all(d.metadata["is_spell"] is False for d in docs)


# --- search -------------------------------------------------------------------


@pytest.fixture
def db():
    from conftest import FakeDB

    return FakeDB()


def test_the_new_type_is_a_selectable_doc_type():
    assert spells.DOC_TYPE_IONAS in search.DOC_TYPES
    assert spells.DOC_TYPE_IONAS in spells.DOC_TYPES
    assert spells.RULE_DOC_TYPES == (spells.DOC_TYPE_SRD, spells.DOC_TYPE_IONAS)


def test_a_rule_from_either_source_reports_Rule_not_a_level(db):
    """Both rule types carry level 0, and calling that "Cantrip" would be a lie a client
    could not detect - which is why the label is derived from the doc type."""
    srd_hit = search.search(db, "", mode="text", doc_type="srd").hits[0]
    assert srd_hit.level_label == "Rule"
    ionas_hit = search._hit({"doc_type": spells.DOC_TYPE_IONAS, "spell_name": "Healing Light",
                             "level": 0})
    assert ionas_hit.level_label == "Rule"


def test_a_rules_row_is_collapsed_by_its_section_not_its_name():
    """The two rule sources share a collection and can share a name - the SRD has a
    ``Fireball`` heading and the corpus has a Fireball spell - so the key has to include
    the source *and* the section."""
    srd_key = search._document_key({"doc_type": "srd", "document": "playing-the-game",
                                    "slug": "cover"})
    other_key = search._document_key({"doc_type": spells.DOC_TYPE_IONAS,
                                      "document": "warlock-subclasses.json",
                                      "slug": "celestial-patron-healing-light"})
    assert srd_key != other_key
    assert srd_key[0] == "srd"
    assert other_key[0] == spells.DOC_TYPE_IONAS


# --- the real source ----------------------------------------------------------


@requires_source
def test_the_real_source_holds_rules_the_srd_does_not():
    """The reason to read it at all: the SRD carries one subclass per class.

    For a Warlock that is the Fiend Patron, so a question about a Celestial Warlock has no
    SRD answer at all.
    """
    names = set(ionas.names())
    assert "Healing Light" in names          # Celestial Patron
    assert "Portent" in names                # Diviner
    assert "Eldritch Invocations" in names


@requires_source
def test_the_real_source_agrees_with_the_srd_where_they_overlap():
    """Where both carry a rule they are the same 2024 text, which is what makes it safe to
    read this as 2024 rather than as a wiki's summary."""
    found = ionas.lookup("Dark One's Blessing")
    assert found is not None
    assert "Temporary Hit Points equal to your Charisma modifier plus your Warlock level" in (
        found["text"]
    )


@requires_source
def test_the_real_source_is_fully_repaired():
    """No scan artifact survives normalisation anywhere in 3.6MB of source.

    A spot check would pass while a section the reader happens to open is still broken, so
    this reads every section.
    """
    broken = ["protec-tion", "w ith", "F ireball", "pro ficienc", "O Hit Points",
              "fe et ", "ta rget", "res tore", "Radi ance", "Inca pacitated"]
    text = "\n".join(section.text for section in ionas.sections())
    for artifact in broken:
        assert artifact not in text, artifact


# --- hierarchy: where a rule sits ---------------------------------------------
#
# The source stores its hierarchy in *filenames and directories*, not in the JSON, so a rule
# read on its own does not say what it belongs to. "Agonizing Blast" is a Warlock invocation
# and nothing in `agonizing-blast.json` says so: the link lives in `eldritch-invocations.json`
# (a router) which is declared by the Warlock's *Eldritch Invocations* feature in a third
# file. That three-file chain is what these tests pin down, because it is the part a reader
# of one file cannot reconstruct.


def test_a_class_feature_sits_under_its_class(source):
    """A feature's name alone does not say which class grants it - "Pact Magic" is not
    obviously a Warlock feature."""
    found = ionas.lookup("Pact Magic")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == ["Classes", "Warlock"]


def test_a_subclass_feature_carries_the_class_above_the_subclass(source):
    """`warlock-subclasses.json` is keyed by subclass and never names the class, so the
    class is recovered from the filename. Without it the trail would start at "Celestial
    Patron" and never say what it is a patron *of*."""
    found = ionas.lookup("Healing Light")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == [
        "Classes", "Warlock", "Celestial Patron",
    ]


def test_a_class_choice_names_the_feature_that_grants_it(source):
    """The three-file link: choice -> router -> declaring feature.

    The file itself says only that this is an *Invocation*, which is a category rather than a
    place in the hierarchy. The trail should name the Warlock and *Eldritch Invocations*.
    """
    found = ionas.lookup("Agonizing Blast")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == [
        "Warlock", "Eldritch Invocations",
    ]


def test_a_class_choice_with_no_router_keeps_its_badge_as_the_parent(source):
    """A choice whose granting feature cannot be traced must not lose its breadcrumb.

    The fixture's router is wired up, so this asserts the *fallback* would still be useful by
    checking the trail is never empty for a class choice - a rule filed under a category is
    still easier to place than a bare name.
    """
    root = ionas.directory()
    (root / "classes" / "classChoices" / "orphan-option.json").write_text(
        json.dumps({"name": "Orphan Option", "badge": "Invocation",
                    "description": "Granted by nothing recorded."})
    )
    ionas.clear_cache()
    found = ionas.lookup("Orphan Option")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == ["Classes", "Invocation"]


def test_an_ambiguous_router_prefers_the_feature_whose_name_matches(source):
    """A router can be declared by more than one feature, and the source does not say which
    is the real parent - so the names have to decide.

    The real source hits this: the Blood Hunter lists `blood-curses` under both *Hemocraft*
    and *Blood Curses*. Nothing in the JSON says which one owns them, but "Blood Curses" is
    obviously the parent of a blood curse, and *Hemocraft* is the class's resource.
    """
    root = ionas.directory()
    (root / "classes" / "blood-hunter.json").write_text(json.dumps({
        "class": "Blood Hunter",
        "features": {
            "1": [{"name": "Hemocraft", "description": "A resource.",
                   "classChoices": ["curses"]}],
            "2": [{"name": "Blood Curses", "description": "Your curses.",
                   "classChoices": ["curses"]}],
        },
    }))
    (root / "classes" / "classChoices" / "curses.json").write_text(
        json.dumps({"curse-of-x": "Curse of X"})
    )
    (root / "classes" / "classChoices" / "curse-of-x.json").write_text(json.dumps({
        "name": "Curse of X", "badge": "Blood Curse", "description": "A curse.",
    }))
    ionas.clear_cache()
    found = ionas.lookup("Curse of X")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == [
        "Blood Hunter", "Blood Curses",
    ]


def test_a_species_trait_sits_under_its_species(source):
    """"Darkvision" is a trait of ten species at once, so the name identifies nothing."""
    found = ionas.lookup("Darkvision")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == ["Species", "Aasimar"]


def test_a_rule_from_a_rules_file_sits_under_that_file(source):
    """A variant rule has no class or species above it - the collection it was published in
    is its only grouping."""
    found = ionas.lookup("One Death Save")
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == [
        "Rules", "Desperate Measures",
    ]


@pytest.mark.parametrize("name", ["Acid Splash", "Alert", "Battleaxe"])
def test_a_flat_entry_has_no_ancestors(source, name):
    """A spell, a feat and an item are single entries with nothing above them.

    An invented trail would be worse than none: it would claim a hierarchy the source does
    not have, and a reader would look for the parent it named.
    """
    found = ionas.lookup(name)
    assert found is not None
    assert found["ancestors"] == []


def test_the_trail_is_numbered_outward_in(source):
    """`level` is the crumb's depth, so a component can indent or truncate on it without
    counting. The SRD's equivalent is the heading level; this source has no heading depth."""
    found = ionas.lookup("Healing Light")
    assert found is not None
    assert [crumb["level"] for crumb in found["ancestors"]] == [1, 2, 3]


def test_no_crumb_pretends_to_be_a_link(source):
    """Every crumb is a label, so every `slug` is empty.

    The source's hierarchy is made of files and folders, and one section is emitted per rule -
    so a crumb names a place with no page of its own. A slug here would send a client looking
    for a rule that does not exist, which is the class of bug this project has paid for
    before: a link that fails looks like a missing rule, not like a missing page.
    """
    for section in ionas.sections():
        for crumb in section.ancestors:
            assert crumb.slug == "", (section.name, crumb)


@requires_source
def test_the_real_source_places_every_class_choice():
    """Almost the point of the exercise: every one of the 73 class choices resolves to the
    class and feature that grant it.

    A silent failure here would be invisible - the choice would keep its weaker category
    crumb and still look fine - so the count is asserted rather than a sample.
    """
    root = ionas.directory()
    owners = ionas._choice_owners(root)
    leaves = [
        ionas._read(path) for path in sorted((root / "classes" / "classChoices").glob("*.json"))
    ]
    names = [
        data["name"] for data in leaves
        if isinstance(data, dict) and "name" in data
    ]
    assert len(names) == 73
    missing = [name for name in names if ionas._fold(name) not in owners]
    assert missing == []


@requires_source
def test_the_real_source_agrees_with_the_routers():
    """The owner index is built by matching a router's display name to the leaf's own name,
    and the routers annotate their entries - `"Agonizing Blast (Level 2+ Warlock, a Warlock
    Cantrip That Deals Damage)"`. If the annotation were not stripped, nothing would match
    and every invocation would silently fall back to the weaker trail.
    """
    every = {ionas._fold(section.name) for section in ionas.sections()}
    root = ionas.directory()
    for router in ("eldritch-invocations", "metamagic", "fighting-styles", "blood-curses"):
        data = ionas._read(root / "classes" / "classChoices" / f"{router}.json")
        assert isinstance(data, dict)
        for display in data.values():
            name = ionas._strip_parenthetical(str(display))
            assert ionas._fold(name) in every, (router, display)


@requires_source
@pytest.mark.parametrize(
    "name,trail",
    [
        ("Pact Magic", ["Classes", "Warlock"]),
        ("Healing Light", ["Classes", "Warlock", "Celestial Patron"]),
        ("Agonizing Blast", ["Warlock", "Eldritch Invocations"]),
        ("Archery", ["Fighter", "Fighting Styles"]),
        ("Careful Spell", ["Sorcerer", "Metamagic"]),
        ("Protector", ["Cleric", "Divine Order"]),
        ("Rite of the Flame", ["Blood Hunter", "Crimson Rite"]),
        ("Darkvision", ["Species", "Aasimar"]),
    ],
)
def test_the_real_source_trails(name, trail):
    """The shapes against real content, because the fixture is one file per kind and the real
    source is where the three-file link actually has to hold."""
    found = ionas.lookup(name)
    assert found is not None
    assert [crumb["text"] for crumb in found["ancestors"]] == trail
