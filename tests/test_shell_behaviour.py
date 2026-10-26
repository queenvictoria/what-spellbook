"""Tests for shell behaviour beyond command parsing: prompt assembly, retrieval
wiring, error handling, and the lazy/import-safe module contract.
"""

import pytest

from backend.libs import cache  # noqa: F401
from backend.libs import llm  # noqa: E402
from backend.cli import app as cli_app
from backend.libs import indexing
from backend.libs import watching


# --- /scenario prompt assembly ---


def test_scenario_sends_character_sheet_into_prompt(shell, fake_llm, fake_db):
    shell.spellbook.character_text = "Name: Lois\nClass: Warlock"
    shell.onecmd("/scenario a burning tavern")

    prompt = fake_llm.prompts[0]
    assert "Name: Lois" in prompt
    assert "Class: Warlock" in prompt


def test_scenario_sends_scenario_text_into_prompt(shell, fake_llm):
    shell.onecmd("/scenario imps pour from the cellar")
    assert "imps pour from the cellar" in fake_llm.prompts[0]


def test_scenario_retrieves_spell_context(shell, fake_llm, fake_db):
    fake_db.docs = [
        type("D", (), {"page_content": "Fireball text", "metadata": {"filename": "fireball.md", "tags": "Fire"}})()
    ]
    fake_db.retriever = type("R", (), {"invoke": lambda self, q: fake_db.docs})()
    shell.onecmd("/scenario anything")

    prompt = fake_llm.prompts[0]
    assert "Fireball text" in prompt
    assert "fireball.md" in prompt


def test_scenario_filters_retrieval_by_eligibility(shell, fake_db):
    """Retrieval now runs through filtered lanes rather than one unfiltered query.

    Every similarity call must carry a filter, so a ranking lane can never widen the
    pool beyond what the character is allowed to prepare.
    """
    shell.onecmd("/scenario anything")
    assert fake_db.as_retriever_calls, "expected at least one filtered retrieval lane"
    assert all("filter" in kwargs for kwargs in fake_db.as_retriever_calls)
    filters = [kwargs["filter"] for kwargs in fake_db.as_retriever_calls]
    assert any({"level": 0} in f["$and"] for f in filters)
    assert any({"ritual": True} in f["$and"] for f in filters)


def test_scenario_queries_retriever_with_scenario(shell, fake_db):
    shell.onecmd("/scenario a duel on a bridge")
    assert "a duel on a bridge" in fake_db.retriever.queries


def test_scenario_prompt_asks_for_three_books(shell, fake_llm):
    shell.onecmd("/scenario anything")
    prompt = fake_llm.prompts[0]
    assert "EXACTLY 3" in prompt
    assert "Book 1" in prompt and "Book 2" in prompt and "Book 3" in prompt


def test_scenario_without_args_does_not_call_llm(shell, fake_llm, caplog):
    with caplog.at_level("ERROR"):
        shell.onecmd("/scenario")
    assert fake_llm.prompts == []
    assert "scenario description" in caplog.text


def test_scenario_with_no_legal_spells_skips_llm(shell, fake_db, fake_llm, capsys):
    """With no eligible book picks there is nothing to recommend, so the model is
    never called. Similarity hits alone are not enough - the lanes must be empty."""
    fake_db.CATALOGUE = []
    shell.onecmd("/scenario anything")
    assert fake_llm.prompts == []
    assert "eligibility" in capsys.readouterr().out


# --- /ask refinement ---


def test_ask_without_prior_scenario_does_not_call_llm(shell, fake_llm, caplog):
    with caplog.at_level("ERROR"):
        shell.onecmd("/ask what about hex?")
    assert fake_llm.prompts == []
    assert "/scenario" in caplog.text


def test_ask_without_question_after_scenario(shell, fake_llm, caplog):
    shell.onecmd("/scenario a fight")
    fake_llm.prompts.clear()
    with caplog.at_level("ERROR"):
        shell.onecmd("/ask")
    assert fake_llm.prompts == []


def test_ask_includes_previous_response_and_original_scenario(shell, fake_llm):
    shell.onecmd("/scenario a fight at dawn")
    fake_llm.prompts.clear()
    shell.onecmd("/ask swap Fireball")

    prompt = fake_llm.prompts[0]
    assert "a fight at dawn" in prompt
    assert "FAKE RESPONSE" in prompt
    assert "swap Fireball" in prompt


# --- LLM error handling ---


def test_llm_failure_is_reported_not_raised(shell, caplog, capsys):
    """A dead backend must not take down the REPL."""

    class Boom:
        def invoke(self, prompt):
            raise RuntimeError("backend down")

    shell.llm = Boom()
    with caplog.at_level("ERROR"):
        shell.onecmd("/scenario anything")
    assert "backend down" in caplog.text
    assert "backend down" in capsys.readouterr().out


def test_llm_failure_leaves_the_previous_answer_intact(shell, capsys):
    """A failed refine must not wipe the books already on screen."""

    class Boom:
        def invoke(self, prompt):
            raise RuntimeError("backend down")

    shell.onecmd("/scenario something")
    before = shell.last.answer
    shell.llm = Boom()
    shell.onecmd("/ask refine it")
    assert shell.last.answer == before
    assert "backend down" in capsys.readouterr().out


# --- response normalisation (moved to backend.llm) ---


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("plain string", "plain string"),
        (type("M", (), {"content": "from content"})(), "from content"),
    ],
)
def test_extract_text_normalises_backends(response, expected):
    assert llm.extract_text(response) == expected


def test_extract_text_prefers_text_attribute():
    class WithText:
        text = "from text"

        def __init__(self):
            self.content = "from content"

    assert llm.extract_text(WithText()) == "from text"


def test_extract_text_calls_text_when_callable():
    class CallableText:
        content = "from content"

        def text(self):
            return "from callable"

    assert llm.extract_text(CallableText()) == "from callable"


def test_extract_text_falls_back_to_str_for_unknown_objects():
    assert llm.extract_text(12345) == "12345"


# --- provenance labels ---


def test_an_interpreted_rule_is_not_labelled_as_a_quotation(shell, capsys):
    """The banner is the only place the REPL says where an answer came from.

    "what is a spell attack" is answered by the glossary's own "Spell Attack" heading, but
    the precise path refuses it, so the answer is the model's reading of related text. The
    banner must not say "from the 2024 SRD", which would present an interpretation as a
    quotation - the same failure as showing a model's guess as a sheet value.
    """
    shell.onecmd("/? what is a spell attack")
    out = capsys.readouterr().out
    assert "interpreted from the 2024 SRD" in out
    assert "from the 2024 SRD" not in out.replace("interpreted from the 2024 SRD", "")


def test_a_quoted_rule_is_labelled_as_one(shell, capsys):
    """The precise path is unchanged, and its label must stay the plain one."""
    shell.onecmd("/? how does cover work")
    out = capsys.readouterr().out
    assert "from the 2024 SRD" in out
    assert "interpreted" not in out


# --- import safety ---


def test_import_builds_no_vector_store():
    """Importing the packages must not scan, embed, or delete anything."""
    assert not hasattr(indexing, "db")


def test_import_defines_no_eager_embeddings():
    """get_embeddings is a factory; the module holds no client until asked."""
    assert callable(indexing.get_embeddings)
    assert getattr(indexing, "_embeddings", None) is None


def test_observer_is_a_factory_not_a_shared_instance():
    """A single Observer cannot be started twice, so each run needs a new one."""
    first = watching.get_observer()
    second = watching.get_observer()
    assert first is not second
    first.stop()
    second.stop()


def test_stop_observer_tolerates_none():
    watching.stop_observer(None)


def test_exit_on_sigterm_raises_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        cli_app._exit_on_sigterm(15, None)
