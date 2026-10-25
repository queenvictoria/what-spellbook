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
    """Minimal vector store exposing the as_retriever surface main uses."""

    def __init__(self, docs=None):
        self.docs = [FakeDoc()] if docs is None else docs
        self.retriever = FakeRetriever(self.docs)
        self.search_kwargs = None

    def as_retriever(self, search_kwargs=None):
        """Mirror langchain's real signature so call sites stay honest."""
        self.search_kwargs = search_kwargs
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
