"""Third-party attribution: what the app owes, and when it owes it.

The interesting property here is not the text — it is *conditional* obligation. The SRD is
vendored, so its notice always applies; the optional rulebook is fetched and read in place,
so its notice applies only when the checkout is installed. A notice for content that is not
there is a claim about a redistribution that never happened, so the presence flag is the
thing worth testing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.libs import config, ionas, licensing

ROOT = Path(__file__).resolve().parent.parent


def test_the_srd_notice_is_always_owed():
    """The SRD is vendored, so its attribution cannot be conditional on anything."""
    srd = next(source for source in licensing.sources() if source.key == "srd")
    assert srd.present is True
    assert srd.licence == "CC-BY-4.0"
    assert "Wizards of the Coast" in srd.attribution


def test_the_optional_rulebook_notice_follows_the_checkout(tmp_path, monkeypatch):
    """Present when the folder is there, absent when it is not - the whole contract."""
    monkeypatch.setattr(config, "IONAS_DIR", str(tmp_path / "missing"))
    absent = next(source for source in licensing.sources() if source.key == "ionas-politis")
    assert absent.present is False

    (tmp_path / "missing").mkdir()
    present = next(source for source in licensing.sources() if source.key == "ionas-politis")
    assert present.present is True


def test_present_sources_filters_to_what_is_installed(tmp_path, monkeypatch):
    """The list an obligation applies to, as opposed to the list a screen shows."""
    monkeypatch.setattr(config, "IONAS_DIR", str(tmp_path / "missing"))
    keys = [source.key for source in licensing.present_sources()]
    assert keys == ["srd"]


def test_the_attribution_is_the_licence_sentence_not_a_paraphrase():
    """CC-BY-4.0 names the sentence it requires, so it is copied rather than rewritten."""
    srd = next(source for source in licensing.sources() if source.key == "srd")
    assert srd.attribution.startswith(
        'This work includes material taken from the System Reference Document 5.2.1'
    )
    assert "https://creativecommons.org/licenses/by/4.0/" in srd.attribution


def test_the_notice_file_and_the_module_agree():
    """A notice that disagrees with itself is worse than no notice.

    The module is what the app renders and ``NOTICE.md`` is what a reader of the repository
    finds. Two copies of a licence sentence will drift, so this pins them together.
    """
    srd = next(source for source in licensing.sources() if source.key == "srd")
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    # The sentence is quoted as a blockquote and wrapped across lines, so the `>` markers and
    # the line breaks both have to go before the two copies can be compared.
    unquoted = re.sub(r"^\s*>\s?", "", notice, flags=re.MULTILINE)
    # The URL is written as a Markdown autolink (`<https://…>`) so it renders as a link; the
    # angle brackets are markup, not part of the sentence.
    unlinked = unquoted.replace("<https://", "https://").replace(">", "")
    collapsed = re.sub(r"\s+", " ", unlinked)
    assert re.sub(r"\s+", " ", srd.attribution) in collapsed


def test_the_provenance_files_are_still_the_long_form():
    """The module is the short form; the records it summarises must still be there."""
    assert (ROOT / "context" / "srd" / "PROVENANCE.md").is_file()
    assert (ROOT / "context" / "DnD-Character-Sheet-Helper.PROVENANCE.md").is_file()


def test_the_optional_source_is_not_redistributed():
    """Its notice says the content is not redistributed, so the directory must be ignored.

    The claim in the attribution is only true while the checkout stays out of the tree. A
    gitlink or a committed copy would make the sentence false, and nothing else would notice.
    """
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "context/DnD-Character-Sheet-Helper/" in ignored


def test_ionas_available_is_the_single_presence_test(tmp_path, monkeypatch):
    """The flag is not a second opinion - it is ``ionas.available()``."""
    monkeypatch.setattr(config, "IONAS_DIR", str(tmp_path / "missing"))
    assert ionas.available() is False
    source = next(s for s in licensing.sources() if s.key == "ionas-politis")
    assert source.present is False
