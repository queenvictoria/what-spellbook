"""Stored ask/chat conversations: a thread of turns under ``.cache/conversations/``.

The rules cache in :mod:`backend.libs.rules` answers *one question* and is keyed on that
question alone. That is the right shape for a lookup and the wrong shape for a
conversation: a follow-up ("and what about a grapple?") is only meaningful beside the
question it follows, and a reader who wants to revisit an exchange wants the exchange,
not a directory of unrelated answers.

So a conversation is a **thread**: an ordered list of turns, each holding the question,
the answer, where the answer came from and what it was grounded in. A thread is keyed by
the character and a hash of its opening question, which is what makes a repeat of the
same opening question *replay* rather than re-ask - the same bargain the run cache makes
for a scenario.

Layout::

    .cache/
      conversations/
        <character>/
          <kind>-<slug>-<hash>.json

One file per thread, holding every turn. A file rather than a directory because a thread
is read whole: the turns are only meaningful in order, and a reader never wants turn 3
without turns 1 and 2.

Nothing here imports LangChain or Chroma, and every function takes an explicit
``cache_dir`` so tests never write to the working tree. Every write is best-effort: a
conversation is a record of an answer, and losing the record must never lose the answer.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import cache

DEFAULT_CACHE_DIR = ".cache"

# The subdirectory, beside ``rules/`` and the per-character run directories.
SUBDIR = "conversations"

# Bump when the entry shape changes in a way an old entry cannot survive - a renamed
# field, a changed meaning, a new required key. An *added* optional key does not need a
# bump: readers already treat a missing key as "no data".
SCHEMA_VERSION = 1

# The kinds of conversation, and what each one is. The kind is part of the key because
# the same words asked of the sheet and of the rulebook are different questions with
# different answers, and a thread must not be continued across the two.
KINDS = ("rules", "character", "selection", "refine")

_WORD = re.compile(r"[a-z0-9]+")
_HASH_LENGTH = 12


def now() -> str:
    """UTC timestamp, always with a timezone.

    Microsecond precision, unlike the run cache's second precision: a listing is ordered
    by ``updated_at``, and several turns of one conversation are appended within the same
    second. At second precision those saves tie, so the order falls back to the id and a
    thread continued just now can sort below one that merely started just now.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalise(text: str) -> str:
    """Fold a question so trivial rewording hits the same thread."""
    return " ".join(str(text).lower().split()).strip(" ?.!")


def fingerprint(text: str) -> str:
    """Short stable hash of a normalised question, used as the thread filename."""
    digest = hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()
    return digest[:_HASH_LENGTH]


def slug(text: str, *, max_length: int = 48) -> str:
    """Readable part of the thread filename, so the directory can be browsed."""
    words = _WORD.findall(normalise(text))
    return ("-".join(words)[:max_length].strip("-")) or "conversation"


def thread_id(kind: str, opening: str) -> str:
    """The stable id of a thread: kind, readable slug, short hash.

    The id is the filename stem, so it is also the handle a client passes back to
    continue the thread. It is derived from the *opening* question rather than the latest
    one, so a thread keeps its identity as it grows.
    """
    return f"{kind}-{slug(opening)}-{fingerprint(opening)}"


def _root(cache_dir=None) -> Path:
    root = Path(cache_dir) if cache_dir is not None else cache.DEFAULT_CACHE_DIR
    return root / SUBDIR


def thread_path(kind: str, opening: str, cache_dir=None) -> Path:
    """``<cache_dir>/conversations/<character>/<id>.json`` - the character is added by
    :func:`save`, which is the only place that knows it."""
    return _root(cache_dir) / f"{thread_id(kind, opening)}.json"


def _character_dir(character: str, cache_dir=None) -> Path:
    return _root(cache_dir) / cache.slug(character)


def path_for(character: str, kind: str, opening: str, cache_dir=None) -> Path:
    """The full path of a thread, character directory included."""
    return _character_dir(character, cache_dir) / f"{thread_id(kind, opening)}.json"


@dataclass
class Turn:
    """One question and its answer, with the provenance a reader needs to trust it."""

    question: str
    answer: str
    source: str
    asked_at: str = field(default_factory=now)
    # The sheet field the answer was quoted from, when it was a lookup.
    field_name: str | None = None
    # The SRD files the answer was grounded in, and the documents it was given.
    citations: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    # True when this turn was served from a stored answer rather than asked again. Kept
    # per turn because a thread can be partly replayed and partly fresh.
    from_cache: bool = False
    model: str | None = None
    # The sheet this answer was produced from. A character answer is only replayable while
    # the sheet is unchanged: an edited sheet gives a different answer to the same
    # question, so a mismatch must be a miss rather than a stale hit.
    sheet_fingerprint: str | None = None
    # For a refinement, the previous answer it refined. A repeat only replays against the
    # same books, for the same reason.
    context_fingerprint: str | None = None

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "answer": self.answer,
            "source": self.source,
            "asked_at": self.asked_at,
            "field_name": self.field_name,
            "citations": list(self.citations or []),
            "attachments": list(self.attachments or []),
            "from_cache": self.from_cache,
            "model": self.model,
            "sheet_fingerprint": self.sheet_fingerprint,
            "context_fingerprint": self.context_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        return cls(
            question=data.get("question", ""),
            answer=data.get("answer", ""),
            source=data.get("source", "model"),
            asked_at=data.get("asked_at") or now(),
            field_name=data.get("field_name"),
            citations=list(data.get("citations") or []),
            attachments=list(data.get("attachments") or []),
            from_cache=bool(data.get("from_cache")),
            model=data.get("model"),
            sheet_fingerprint=data.get("sheet_fingerprint"),
            context_fingerprint=data.get("context_fingerprint"),
        )


@dataclass
class Conversation:
    """A thread: an opening question, its kind, and every turn that followed."""

    id: str
    kind: str
    character: str
    opening: str
    turns: list[Turn] = field(default_factory=list)
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)
    # The run this thread belongs to, when it was started from a book. A refine thread is
    # meaningless without it, and a selection thread is easier to read beside it.
    run_id: str | None = None
    path: str | None = None

    @property
    def title(self) -> str:
        """The opening question, for a listing."""
        return self.opening

    @property
    def last_answer(self) -> str:
        return self.turns[-1].answer if self.turns else ""

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "kind": self.kind,
            "character": self.character,
            "opening": self.opening,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [turn.to_dict() for turn in self.turns],
        }

    @classmethod
    def from_dict(cls, data: dict, *, path=None) -> "Conversation":
        return cls(
            id=data.get("id", ""),
            kind=data.get("kind", "rules"),
            character=data.get("character", ""),
            opening=data.get("opening", ""),
            turns=[Turn.from_dict(t) for t in data.get("turns") or []],
            created_at=data.get("created_at") or now(),
            updated_at=data.get("updated_at") or now(),
            run_id=data.get("run_id"),
            path=str(path) if path else None,
        )


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load(character: str, kind: str, opening: str, cache_dir=None) -> Conversation | None:
    """A stored thread, or ``None`` when there is not one.

    A thread written by an older schema is refused rather than half-read: the turns are
    the whole value, and a reader that silently drops them would report an empty
    conversation as a stored one.
    """
    path = path_for(character, kind, opening, cache_dir)
    data = _read(path)
    if not data or data.get("schema_version") != SCHEMA_VERSION:
        return None
    if not data.get("turns"):
        return None
    return Conversation.from_dict(data, path=path)


def load_by_id(character: str, conversation_id: str, cache_dir=None) -> Conversation | None:
    """A stored thread by its id, which is what a client holds."""
    path = _character_dir(character, cache_dir) / f"{conversation_id}.json"
    data = _read(path)
    if not data or data.get("schema_version") != SCHEMA_VERSION:
        return None
    return Conversation.from_dict(data, path=path)


def save(conversation: Conversation, cache_dir=None) -> Path:
    """Write a thread, creating its character directory. Never raises.

    Best-effort on purpose: the answer has already been produced by the time this runs,
    and a full disk must not turn a working answer into an error.
    """
    path = path_for(conversation.character, conversation.kind, conversation.opening, cache_dir)
    conversation.updated_at = now()
    conversation.path = str(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(conversation.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        logging.warning(f"Could not store the conversation ({e}).")
    return path


def append(character: str, kind: str, opening: str, turn: Turn, *,
           run_id: str | None = None, cache_dir=None) -> Conversation:
    """Add a turn to a thread, creating the thread when it does not exist yet.

    The opening question is what identifies the thread, so the first turn's question *is*
    the opening. A later turn is appended to the same file, which is what makes a
    follow-up readable beside the question it followed.
    """
    conversation = load(character, kind, opening, cache_dir)
    if conversation is None:
        conversation = Conversation(
            id=thread_id(kind, opening), kind=kind, character=character,
            opening=opening, run_id=run_id,
        )
    if run_id and not conversation.run_id:
        conversation.run_id = run_id
    conversation.turns.append(turn)
    save(conversation, cache_dir)
    return conversation


def list_threads(cache_dir=None, *, character: str | None = None,
                 kind: str | None = None) -> list[Conversation]:
    """Every stored thread, newest first; optionally filtered by character and kind.

    Newest first because a listing is read to find the recent one, and a thread's
    ``updated_at`` moves as it grows - so a conversation continued today sorts above one
    that merely started today.
    """
    root = _root(cache_dir)
    if not root.is_dir():
        return []

    pattern = f"{cache.slug(character)}/*.json" if character else "*/*.json"
    threads = []
    for path in root.glob(pattern):
        data = _read(path)
        if not data or data.get("schema_version") != SCHEMA_VERSION:
            continue
        if kind and data.get("kind") != kind:
            continue
        threads.append(Conversation.from_dict(data, path=path))
    # Newest first, with the id as a final tie-break. Timestamps are second-precision, so
    # two threads touched in the same second would otherwise sort by whatever order the
    # filesystem returned - a listing that reorders itself between runs.
    return sorted(
        threads,
        key=lambda c: (c.updated_at or "", c.created_at or "", c.id),
        reverse=True,
    )


def find(reference: str, cache_dir=None, *, character: str | None = None,
         kind: str | None = None) -> Conversation | None:
    """Resolve a reference to a thread: an id, a path, or a fragment of its opening.

    A fragment is accepted so a reader can type a few words of the question rather than
    an id, which is the same bargain ``/read`` makes for a run.
    """
    candidate = Path(reference)
    if candidate.is_file():
        data = _read(candidate)
        if data and data.get("schema_version") == SCHEMA_VERSION:
            return Conversation.from_dict(data, path=candidate)

    threads = list_threads(cache_dir, character=character, kind=kind)
    if not threads:
        return None

    needle = reference.strip().lower().replace("\\", "/")
    if not needle:
        return None

    for conversation in threads:
        if conversation.id.lower() == needle:
            return conversation
    for conversation in threads:
        if str(conversation.path or "").lower().endswith(needle):
            return conversation
    for conversation in threads:
        if needle in conversation.opening.lower():
            return conversation
    return None


def replay(conversation: Conversation | None, question: str, *,
           sheet_fingerprint: str | None = None,
           context_fingerprint: str | None = None) -> Turn | None:
    """The stored turn that already answers ``question``, or ``None``.

    A repeat of the same question is served from the thread rather than asked again, which
    is the whole point of storing it. The guards are what keep that honest:

    - The question must match after normalisation, so trivial rewording still hits.
    - A character answer is only valid while the sheet is unchanged. An edited sheet gives
      a different answer to the same question, so a fingerprint mismatch is a miss.
    - A refinement is only valid against the same previous answer, for the same reason.

    The *latest* matching turn wins, so a thread that was answered, edited and answered
    again replays the answer that reflects the current state.
    """
    if conversation is None:
        return None
    wanted = normalise(question)
    for turn in reversed(conversation.turns):
        if normalise(turn.question) != wanted:
            continue
        if sheet_fingerprint is not None and turn.sheet_fingerprint != sheet_fingerprint:
            continue
        if context_fingerprint is not None and turn.context_fingerprint != context_fingerprint:
            continue
        return turn
    return None


def history_block(turns, *, limit: int = 6) -> str:
    """The prior turns of a thread, rendered for a prompt, or an empty string.

    Only the last few turns are carried: a thread is unbounded and a prompt is not, and
    the most recent exchange is what a follow-up refers to. The block is deliberately
    plain - it is context for the model, not a transcript to be reproduced.
    """
    recent = list(turns)[-limit:]
    if not recent:
        return ""
    lines = []
    for turn in recent:
        lines.append(f"Q: {turn.question.strip()}")
        lines.append(f"A: {turn.answer.strip()}")
    return "\n".join(lines)
