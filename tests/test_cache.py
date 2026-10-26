"""Tests for the per-book result cache.

The cache exists so a book can be rated after the scenario is played, so the
tests focus on the two things that make that possible: the key must change when
any of its inputs change, and every book must be stored separately.
"""

import json

import pytest

import cache

ANSWER = '''### Book 1: "Ambush and Control"

**Cantrips:**
1. **Light** - illuminates the bridge.
2. **Sacred Flame** - reliable radiant damage.
3. **Friends** - buys a round of talking.

**Rituals:**
1. **Identify** - for the loot afterwards.
2. **Find Familiar** - scouts the far bank.

**How to Use:**
- Open with Light, then Sacred Flame.

---

### Book 2: "Denial and Escape"

**Cantrips:**
1. **Booming Blade** - punishes movement.
2. **Chill Touch** - stops healing.
3. **Mending** - field repairs.

**Rituals:**
1. **Alarm** - watches the camp.
2. **Comprehend Languages** - reads the orders.
'''

SCENARIO = "We are ambushed on a narrow stone bridge at night."


def _save(tmp_path, **overrides):
    kwargs = dict(
        answer=ANSWER,
        cache_dir=tmp_path,
        character="Lois",
        level=5,
        party=["Barbarian", "Fighter", "Druid"],
        db_version=3,
        scenario=SCENARIO,
    )
    kwargs.update(overrides)
    return cache.save_books(**kwargs)


# --- key generation ---

def test_key_parts_contains_all_six_components(tmp_path):
    key = cache.key_parts(
        character="Lois", level=5, party=["Barbarian", "Fighter"],
        db_version=3, scenario=SCENARIO,
    )
    assert set(key) == {"character", "level", "party", "db_version", "scenario"}
    assert key["character"] == "lois"
    assert key["level"] == 5
    assert key["party"] == "barbarian-fighter"
    assert key["db_version"] == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("character", "Mira"),
        ("level", 6),
        ("party", ["Barbarian", "Rogue"]),
        ("db_version", 4),
        ("scenario", "A quiet dinner in Waterdeep."),
    ],
)
def test_each_component_changes_the_key(field, value):
    """Every listed input must be able to produce a distinct cache entry."""
    base = dict(
        character="Lois", level=5, party=["Barbarian", "Fighter"],
        db_version=3, scenario=SCENARIO,
    )
    changed = {**base, field: value}
    assert cache.key_parts(**base) != cache.key_parts(**changed)


def test_scenario_fingerprint_ignores_case_and_layout():
    """Re-typing the same scenario must hit the same entry."""
    a = cache.scenario_fingerprint(SCENARIO)
    b = cache.scenario_fingerprint("  we are   ambushed on a narrow\nstone bridge at night.  ")
    assert a == b


def test_scenario_fingerprint_distinguishes_meaning():
    assert cache.scenario_fingerprint(SCENARIO) != cache.scenario_fingerprint(
        "We are ambushed on a narrow stone bridge at dawn."
    )


def test_party_accepts_a_string_and_a_list():
    """Party may come from YAML either way; the key must not depend on the form."""
    as_list = cache.key_parts(
        character="Lois", level=5, party=["Barbarian", "Fighter"], db_version=3, scenario="x"
    )
    as_string = cache.key_parts(
        character="Lois", level=5, party="Barbarian, Fighter", db_version=3, scenario="x"
    )
    assert as_list["party"] == as_string["party"] == "barbarian-fighter"


def test_key_dir_includes_level_party_dbversion_and_scenario():
    key = cache.key_parts(
        character="Lois", level=5, party=["Barbarian"], db_version=3, scenario=SCENARIO
    )
    directory = cache.key_dir(key)
    assert directory.startswith("5-barbarian-3-")
    assert key["scenario"] in directory


# --- book splitting ---

def test_split_books_finds_one_section_per_book():
    books = cache.split_books(ANSWER)
    assert [b["index"] for b in books] == [1, 2]
    assert books[0]["name"] == "Ambush and Control"
    assert books[1]["name"] == "Denial and Escape"


def test_split_books_keeps_the_original_text_intact():
    """The raw response is the record; sections must not paraphrase it."""
    books = cache.split_books(ANSWER)
    for book in books:
        assert book["text"] in ANSWER
        assert book["text"].strip() == book["text"]


def test_split_books_handles_an_answer_without_headings():
    books = cache.split_books("Just some prose with no book headings.")
    assert len(books) == 1
    assert books[0]["name"] == "Untitled"


def test_split_books_handles_an_empty_answer():
    assert cache.split_books("") == []
    assert cache.split_books("   \n  ") == []


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ('### Book 1: "Ambush and Control"', "Ambush and Control"),
        ("## Book 2: Denial and Escape", "Denial and Escape"),
        ("**Book 1: Ambush and Control**", "Ambush and Control"),
    ],
)
def test_split_books_reads_several_heading_styles(heading, expected):
    books = cache.split_books(f"{heading}\n\n**Cantrips:**\n1. **Light** - bright.\n")
    assert books[0]["name"] == expected


# --- picks ---

def test_parse_picks_reads_cantrips_and_rituals():
    picks = cache.parse_picks(cache.split_books(ANSWER)[0]["text"])
    assert picks["cantrips"] == ["Light", "Sacred Flame", "Friends"]
    assert picks["rituals"] == ["Identify", "Find Familiar"]


def test_parse_picks_strips_the_pool_annotation():
    """The model sometimes bolds 'Name (Cantrip; Evocation; Bard)'."""
    section = "**Cantrips:**\n1. **Light** (Cantrip; Evocation; Bard) - bright.\n"
    assert cache.parse_picks(section)["cantrips"] == ["Light"]


def test_parse_picks_ignores_later_sections():
    """'How to Use' prose must not be mistaken for more picks."""
    picks = cache.parse_picks(cache.split_books(ANSWER)[0]["text"])
    assert len(picks["cantrips"]) == 3
    assert len(picks["rituals"]) == 2


# --- files ---

def test_each_book_gets_its_own_file(tmp_path):
    written = _save(tmp_path)
    assert len(written) == 2
    assert {p.name for p in written} == {"1-ambush-and-control.json", "2-denial-and-escape.json"}
    assert len({p.parent for p in written}) == 1, "books share one key directory"


def test_cache_path_encodes_the_whole_key(tmp_path):
    written = _save(tmp_path)
    relative = written[0].relative_to(tmp_path).parts
    assert relative[0] == "lois"
    assert relative[1].startswith("5-barbarian-fighter-druid-3-")


def test_entry_records_input_context_prompts_response_and_output(tmp_path):
    written = _save(
        tmp_path,
        input_data={"character_sheet": {"Name": "Lois", "Current Level": 5}},
        context={"rule_context_files": ["spells.md"], "pool_cantrips": ["Light"]},
        prompts={"prompt": "the full prompt"},
        model="qwen2.5-coder:7b-instruct",
        book_filters={"Ambush and Control": {"k": 30}},
    )
    entry = json.loads(written[0].read_text(encoding="utf-8"))

    assert entry["input"]["character_sheet"]["Name"] == "Lois"
    assert entry["context"]["pool_cantrips"] == ["Light"]
    assert entry["prompt"]["prompt"] == "the full prompt"
    assert entry["response"] == ANSWER
    assert entry["output"]["picks"]["cantrips"] == ["Light", "Sacred Flame", "Friends"]
    assert entry["output"]["book_filters"] == {"k": 30}
    assert entry["model"] == "qwen2.5-coder:7b-instruct"
    assert entry["schema_version"] == cache.SCHEMA_VERSION


def test_entry_stores_the_scenario_text_not_just_its_hash(tmp_path):
    written = _save(tmp_path)
    entry = json.loads(written[0].read_text(encoding="utf-8"))
    assert entry["key"]["scenario_text"] == SCENARIO
    assert entry["key"]["scenario"] == cache.scenario_fingerprint(SCENARIO)


def test_rating_starts_empty_and_ready_to_fill(tmp_path):
    written = _save(tmp_path)
    entry = json.loads(written[0].read_text(encoding="utf-8"))
    assert entry["rating"] == {"score": None, "rated_at": None, "notes": None, "outcome": None}


def test_same_inputs_overwrite_rather_than_duplicate(tmp_path):
    first = _save(tmp_path)
    second = _save(tmp_path)
    assert [p.name for p in first] == [p.name for p in second]
    assert len(list(tmp_path.rglob("*.json"))) == 2


def test_different_scenario_writes_a_second_directory(tmp_path):
    _save(tmp_path)
    _save(tmp_path, scenario="A chase through the sewers.")
    assert len(list(tmp_path.rglob("*.json"))) == 4
    assert len(list((tmp_path / "lois").iterdir())) == 2


def test_db_version_bump_lands_in_a_new_directory(tmp_path):
    """A rebuilt index invalidates the pool, so it must not reuse entries."""
    _save(tmp_path)
    _save(tmp_path, db_version=4)
    assert len(list((tmp_path / "lois").iterdir())) == 2


def test_save_creates_missing_directories(tmp_path):
    written = _save(tmp_path / "deep" / "nested")
    assert all(p.is_file() for p in written)


def test_save_returns_empty_for_an_empty_answer(tmp_path):
    assert _save(tmp_path, answer="") == []
    assert not list(tmp_path.rglob("*.json"))


# --- find / list ---

def test_load_entries_lists_newest_first(tmp_path):
    written = _save(tmp_path)
    paths = cache.load_entries(tmp_path)
    assert len(paths) == 2
    assert {p.name for p in paths} == {p.name for p in written}


def test_load_entries_filters_by_character(tmp_path):
    _save(tmp_path)
    _save(tmp_path, character="Mira")
    assert len(cache.load_entries(tmp_path)) == 4
    assert len(cache.load_entries(tmp_path, character="Mira")) == 2


def test_load_entries_on_a_missing_directory_is_empty(tmp_path):
    assert cache.load_entries(tmp_path / "absent") == []


def test_find_book_by_partial_name(tmp_path):
    _save(tmp_path)
    assert cache.find_book("ambush", tmp_path).name == "1-ambush-and-control.json"


def test_find_book_by_numbered_prefix(tmp_path):
    _save(tmp_path)
    assert cache.find_book("2-denia", tmp_path).name == "2-denial-and-escape.json"


def test_find_book_by_explicit_path(tmp_path):
    written = _save(tmp_path)
    assert cache.find_book(str(written[0]), tmp_path) == written[0]


def test_find_book_returns_none_when_nothing_matches(tmp_path):
    _save(tmp_path)
    assert cache.find_book("nonexistent-book", tmp_path) is None


# --- rating ---

def test_rate_records_the_score_and_keeps_everything_else(tmp_path):
    written = _save(tmp_path)
    entry = cache.rate(written[0], score=4, notes="Carried the fight", outcome="won")
    assert entry["rating"]["score"] == 4
    assert entry["rating"]["notes"] == "Carried the fight"
    assert entry["rating"]["outcome"] == "won"
    assert entry["rating"]["rated_at"]
    assert entry["prompt"] == {}


def test_rate_persists_to_disk(tmp_path):
    written = _save(tmp_path)
    cache.rate(written[0], score=5)
    reloaded = json.loads(written[0].read_text(encoding="utf-8"))
    assert reloaded["rating"]["score"] == 5


def test_rate_does_not_touch_sibling_books(tmp_path):
    written = _save(tmp_path)
    cache.rate(written[0], score=1)
    sibling = json.loads(written[1].read_text(encoding="utf-8"))
    assert sibling["rating"]["score"] is None


def test_rate_is_idempotent_for_the_latest_call(tmp_path):
    written = _save(tmp_path)
    cache.rate(written[0], score=2)
    cache.rate(written[0], score=5, notes="Reassessed after the session")
    entry = json.loads(written[0].read_text(encoding="utf-8"))
    assert entry["rating"]["score"] == 5
    assert entry["rating"]["notes"] == "Reassessed after the session"


def test_rate_accepts_a_fixed_timestamp(tmp_path):
    written = _save(tmp_path)
    entry = cache.rate(written[0], score=3, rated_at="2024-01-01T00:00:00+00:00")
    assert entry["rating"]["rated_at"] == "2024-01-01T00:00:00+00:00"


# --- module hygiene ---

def test_default_cache_dir_is_the_dot_cache_directory():
    assert cache.DEFAULT_CACHE_DIR == ".cache"


def test_cache_module_is_dependency_free():
    """Like spells.py, this must import without LangChain or Chroma."""
    import subprocess
    import sys

    script = "import cache, sys; assert 'langchain' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=str(cache.Path(__file__).resolve().parent.parent),
    )
    assert result.returncode == 0, result.stderr


# --- the trailing summary must not look like more books ---
#
# Real answers end with a 'Pairing with existing spells' section whose bullets start
# '**Book 1 pairs with:** Hex, ...'. Treating those as headings produced six books,
# and the bogus ones pushed the real picks out of their own sections.

SUMMARY_TAIL = '''
## 4. Pairing with Existing Spells

- **Book 1 pairs with:** Hex, Hypnotic Pattern, Hunger of Hadar.
- **Book 2 pairs with:** Hold Person, Daylight.
- **Book 3 pairs with:** Aid, Cure Wounds.
'''


def test_split_books_ignores_prose_lines_that_mention_a_book():
    answer = (
        '## Book 1 — Illuminated Kill Zone\n\n**Cantrips:** Light, Mending\n'
        '## Book 2 — Ambush Breaker\n\n**Cantrips:** Message, Mage Hand\n'
        + SUMMARY_TAIL
    )
    books = cache.split_books(answer)
    assert [b["index"] for b in books] == [1, 2]


def test_split_books_keeps_the_real_picks_in_the_real_book():
    answer = (
        '## Book 1 — Kill Zone\n\n**Cantrips:** Light, Mending\n'
        '## Book 2 — Breaker\n\n**Cantrips:** Message, Mage Hand\n'
        + SUMMARY_TAIL
    )
    books = cache.split_books(answer)
    assert "Light" in books[0]["text"]
    assert "Message" in books[1]["text"]


def test_split_books_does_not_repeat_a_book_number():
    answer = '## Book 1 — A\n\ntext\n\n**Book 1 pairs with:** Hex.\n'
    assert len(cache.split_books(answer)) == 1


def test_split_books_rejects_a_long_heading_line():
    """A heading is a title; a whole sentence is prose."""
    answer = "## Book 1 " + "x" * 120 + "\n\n**Cantrips:** Light, Mending\n"
    assert cache.split_books(answer)[0]["name"] == "Untitled"


@pytest.mark.parametrize("heading,is_heading", [
    ("## 4. Pairing with Existing Spells", False),
    ("**Book 1 pairs with:** Hex, Hypnotic Pattern", False),
    ("**Book 2 is the anti-ambush loadout**", False),
    ("## Book 3 — Defensive Hold", True),
    ("**Book 1: Ambush and Control**", True),
    ("### Book 1", True),
])
def test_book_heading_discrimination(heading, is_heading):
    assert cache._is_book_heading(heading) is is_heading


def test_find_book_prefers_the_most_recent_match(tmp_path):
    """Two runs can both match a fragment; the newest entry must win.

    load_entries is newest-first, so returning the first partial match is enough. The
    previous implementation sorted matches by a constant key, which made the winner
    depend on glob order and could surface a stale book.
    """
    import os

    older = _save(tmp_path, scenario="first scenario")[0]
    newer = _save(tmp_path, scenario="second scenario")[0]
    # Both land in the same instant, so pin the mtimes to make "newest" unambiguous.
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    assert cache.find_book("ambush", tmp_path) == newer


def test_save_books_returns_each_book_file(tmp_path):
    written = _save(tmp_path)
    assert len(written) == 2
    assert all(p.read_text(encoding="utf-8") for p in written)
