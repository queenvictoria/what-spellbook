"""Tests for extracting and parsing D&D Beyond PDF character sheets."""

import subprocess

import pytest

from backend.libs import character_import, llm


PDF = b"%PDF-1.7\nexample"
MODEL_YAML = 'Name: "Lois Vale"\nClass: Warlock\nCurrent Level: "5"\n'


def test_extract_pdf_text_preserves_layout(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=b"Name  Class\nLois  Warlock\n")

    monkeypatch.setattr(character_import.subprocess, "run", run)

    text = character_import.extract_pdf_text(PDF)

    assert text == "Name  Class\nLois  Warlock"
    assert seen["command"] == ["pdftotext", "-layout", "-", "-"]
    assert seen["kwargs"]["input"] == PDF


@pytest.mark.parametrize("content", [b"", b"not a PDF"])
def test_extract_rejects_non_pdf(content):
    with pytest.raises(character_import.CharacterImportError, match="not a valid PDF"):
        character_import.extract_pdf_text(content)


def test_extract_rejects_pdf_without_text(monkeypatch):
    monkeypatch.setattr(
        character_import.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=b" \n"),
    )

    with pytest.raises(character_import.CharacterImportError, match="no extractable text"):
        character_import.extract_pdf_text(PDF)


def test_parse_pdf_returns_sanitized_filename_and_canonical_yaml(monkeypatch):
    monkeypatch.setattr(
        character_import.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"Name  Lois Vale"
        ),
    )
    prompts_seen = []

    def invoke(model, prompt):
        prompts_seen.append(prompt)
        return f"```yaml\n{MODEL_YAML}```"

    monkeypatch.setattr(llm, "invoke", invoke)

    stem, data, rendered = character_import.parse_character_pdf(
        PDF, filename="sheet.pdf", model=object(),
    )

    assert stem == "Lois-Vale"
    assert data == {"Name": "Lois Vale", "Class": "Warlock", "Current Level": "5"}
    assert "Current Level: '5'" in rendered
    assert "Name  Lois Vale" in prompts_seen[0]


def test_parse_pdf_rejects_unsupported_model_fields(monkeypatch):
    monkeypatch.setattr(
        character_import.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"character text"
        ),
    )
    monkeypatch.setattr(
        llm, "invoke", lambda *args, **kwargs: "Name: Lois\nSecret: value\n"
    )

    with pytest.raises(character_import.CharacterImportError, match="unsupported"):
        character_import.parse_character_pdf(PDF, filename="sheet.pdf", model=object())


def test_parse_pdf_leaves_model_errors_typed(monkeypatch):
    monkeypatch.setattr(
        character_import.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=b"character text"
        ),
    )
    monkeypatch.setattr(
        llm,
        "invoke",
        lambda *args, **kwargs: (_ for _ in ()).throw(llm.EmptyCompletion("empty")),
    )

    with pytest.raises(llm.EmptyCompletion):
        character_import.parse_character_pdf(PDF, filename="sheet.pdf", model=object())
