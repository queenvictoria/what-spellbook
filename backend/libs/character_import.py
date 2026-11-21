"""Import helpers for converting a D&D Beyond PDF into a reviewable YAML sheet."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from . import llm, prompts

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_TEXT_CHARS = 60_000
PDF_TIMEOUT_SECONDS = 30


class CharacterImportError(ValueError):
    """Raised when a PDF or extracted character sheet cannot be parsed."""


def extract_pdf_text(content: bytes) -> str:
    """Extract layout-preserving text using Poppler's ``pdftotext``."""
    if not content.startswith(b"%PDF-"):
        raise CharacterImportError("The selected file is not a valid PDF.")
    if len(content) > MAX_PDF_BYTES:
        raise CharacterImportError("PDF files must be no larger than 20 MB.")

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=content,
            capture_output=True,
            timeout=PDF_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as e:
        raise CharacterImportError(
            "PDF import requires Poppler's pdftotext command. Install Poppler and retry."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise CharacterImportError("The PDF took too long to read.") from e

    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CharacterImportError(
            f"Could not read the PDF{': ' + detail if detail else '.'}"
        )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        raise CharacterImportError(
            "The PDF contains no extractable text. Scanned images are not supported."
        )
    if len(text) > MAX_PDF_TEXT_CHARS:
        raise CharacterImportError(
            "The extracted PDF text is too long to parse safely (maximum 60,000 characters)."
        )
    return text


def parse_character_pdf(content: bytes, *, filename: str, model) -> tuple[str, dict, str]:
    """Extract and parse a PDF, returning a safe suggested name, mapping and YAML."""
    text = extract_pdf_text(content)
    completion = llm.invoke(model, prompts.character_sheet_prompt(text))
    yaml_text = completion.strip()
    if yaml_text.startswith("```"):
        lines = yaml_text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            yaml_text = "\n".join(lines[1:-1]).strip()

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise CharacterImportError(
            "The model did not return valid YAML. Try parsing again or edit a YAML sheet."
        ) from e
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise CharacterImportError(
            "The model did not return a YAML mapping. Try parsing again."
        )

    unsupported = sorted(set(data) - set(prompts.CHARACTER_SHEET_KEYS))
    if unsupported:
        raise CharacterImportError(
            "The model returned unsupported sheet fields: " + ", ".join(unsupported)
        )

    display_name = str(data.get("Name") or Path(filename).stem).strip()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", display_name).strip("._-")[:64]
    if not stem or stem in {".", ".."}:
        stem = "character"
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return stem, data, rendered
