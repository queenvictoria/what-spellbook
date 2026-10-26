"""Shared fixtures for the what-spellbook test suite."""

import sys
from pathlib import Path

import pytest

# Make the repo root importable so tests can `import main` regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


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
def shell(monkeypatch, fake_db, fake_llm):
    """A SpellbookShell wired to fakes, with no real LLM or vector store contact."""
    monkeypatch.setattr(main, "build_llm", lambda: fake_llm)
    instance = main.SpellbookShell(vector_db=fake_db, character_context="Class: Warlock")
    instance.llm = fake_llm
    return instance


@pytest.fixture
def character_dir(tmp_path, monkeypatch):
    """Point main.CHARACTERS_DIR at an empty temp directory of character sheets."""
    monkeypatch.setattr(main, "CHARACTERS_DIR", tmp_path)
    return tmp_path
