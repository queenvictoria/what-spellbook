"""Shared fixtures for the what-spellbook test suite."""

import sys
from pathlib import Path

import pytest

# The repo root is the import root, so `backend.*` resolves from anywhere. pytest also
# inserts rootdir for us, but doing it explicitly means `pytest tests/foo.py` and a bare
# `pytest` behave identically.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.libs import cache, characters, config, service  # noqa: E402
from backend.cli import progress as progress_mod  # noqa: E402
from backend.cli.shell import SpellbookShell  # noqa: E402



class FakeDoc:
    """Stand-in for a langchain Document returned by the retriever."""

    def __init__(self, page_content="Fireball: 8d6 fire damage.", **metadata):
        self.page_content = page_content
        self.metadata = metadata or {"filename": "fireball.md", "tags": "Level3, Fire"}


class FakeRetriever:
    def __init__(self, docs):
        self._docs = docs
        self.queries = []

    def invoke(self, query):
        self.queries.append(query)
        return self._docs


class FakeDB:
    """Minimal vector store exposing the surface main uses.

    Implements a small catalogue and a naive ``where`` matcher for the operators main
    actually generates ($and/$or/$nin/equality/$lte), so eligibility lanes are
    exercised for real instead of returning a canned payload.
    """

    CATALOGUE = [
        {"filename": "Acid Splash.md", "spell_name": "Acid Splash", "level": 0,
         "ritual": False, "is_spell": True, "school": "Evocation", "classes": "Sorcerer"},
        {"filename": "Fire Bolt.md", "spell_name": "Fire Bolt", "level": 0,
         "ritual": False, "is_spell": True, "school": "Evocation", "classes": "Sorcerer"},
        {"filename": "Detect Magic.md", "spell_name": "Detect Magic", "level": 1,
         "ritual": True, "is_spell": True, "school": "Divination", "classes": "Wizard"},
        {"filename": "Fireball.md", "spell_name": "Fireball", "level": 3,
         "ritual": False, "is_spell": True, "school": "Evocation", "classes": "Wizard"},
        {"filename": "Misty Step.md", "spell_name": "Misty Step", "level": 2,
         "ritual": False, "is_spell": True, "school": "Conjuration", "classes": "Sorcerer"},
        {"filename": "Armblade.md", "spell_name": "Armblade", "level": -1,
         "ritual": False, "is_spell": False, "school": "", "classes": ""},
    ]

    def __init__(self, docs=None):
        self.docs = [FakeDoc()] if docs is None else docs
        self.retriever = FakeRetriever(self.docs)
        self.search_kwargs = None
        self.as_retriever_calls = []
        self.get_calls = []

    @classmethod
    def _matches(cls, row: dict, where) -> bool:
        if not where:
            return True
        for key, expected in where.items():
            if key == "$and":
                if not all(cls._matches(row, c) for c in expected):
                    return False
            elif key == "$or":
                if not any(cls._matches(row, c) for c in expected):
                    return False
            elif isinstance(expected, dict):
                for op, operand in expected.items():
                    actual = row.get(key)
                    if op == "$nin" and actual in operand:
                        return False
                    if op == "$in" and actual not in operand:
                        return False
                    if op == "$lte" and not (isinstance(actual, int) and actual <= operand):
                        return False
                    if op == "$gt" and not (isinstance(actual, int) and actual > operand):
                        return False
            elif row.get(key) != expected:
                return False
        return True

    def get(self, where=None, include=None, **kwargs):
        """Stand-in for Chroma's exhaustive metadata lookup, filtering the catalogue."""
        self.get_calls.append(where)
        rows = [r for r in self.CATALOGUE if self._matches(r, where)]
        return {"metadatas": rows, "ids": [r["filename"] for r in rows]}

    def as_retriever(self, search_kwargs=None):
        """Mirror langchain's real signature so call sites stay honest."""
        self.search_kwargs = search_kwargs
        self.as_retriever_calls.append(search_kwargs or {})
        return self.retriever


class FakeLLM:
    def __init__(self, response="FAKE RESPONSE"):
        self.response = response
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def spellbook(fake_db, fake_llm, tmp_path):
    """A SpellbookService wired to fakes, with no real LLM or vector store contact."""
    return service.SpellbookService(
        fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path / "cache")
    )


@pytest.fixture
def shell(spellbook, fake_llm):
    """A SpellbookShell wired to fakes, with no real LLM or vector store contact."""
    instance = SpellbookShell(spellbook, show_progress=False)
    instance.llm = fake_llm
    return instance


@pytest.fixture
def character_dir(tmp_path, monkeypatch):
    """Point the character directory at a temp directory of character sheets."""
    monkeypatch.setattr(config, "CHARACTERS_DIR", str(tmp_path))
    return tmp_path


BOOKS_ANSWER = '''### Book 1: "Ambush and Control"

**Cantrips:**
1. **Light** - illuminates the bridge.
2. **Sacred Flame** - reliable radiant damage.
3. **Friends** - buys a round of talking.

**Rituals:**
1. **Identify** - for the loot afterwards.

---

### Book 2: "Denial and Escape"

**Cantrips:**
1. **Booming Blade** - punishes movement.
2. **Chill Touch** - stops healing.
3. **Mending** - field repairs.

**Rituals:**
1. **Alarm** - watches the camp.
'''


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect cache writes to a temp directory so tests never touch the working tree."""
    target = tmp_path / "cache"
    monkeypatch.setattr(config, "CACHE_DIR", str(target))
    return target


@pytest.fixture
def loaded_shell(shell, cache_dir):
    """A shell with a character sheet and one generated answer already cached."""
    sheet = {
        "Name": "Lois",
        "Class": "Warlock",
        "Current Level": 5,
        "Party": "Barbarian, Fighter, Druid",
    }
    shell.spellbook.character = sheet
    shell.spellbook.character_text = characters.format_character(sheet)
    shell.spellbook.cache_dir = str(cache_dir)
    shell.cache_dir = str(cache_dir)
    shell.llm.response = BOOKS_ANSWER
    shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    return shell
