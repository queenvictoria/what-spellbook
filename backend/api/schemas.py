"""Pydantic schemas for the HTTP API.

These mirror the backend dataclasses (``service.Generation``, ``service.Book``,
``service.Answer``) rather than reusing them, for two reasons:

* The dataclasses are internal and free to change; the wire format is a contract the
  front end is built against, so a rename should be a deliberate edit here.
* A dataclass field like ``Book.picks`` is a loose ``dict``; the API states the shape so
  a client gets a typed response instead of guessing.

``from_generation`` is the single conversion point, so the mapping lives in one place
instead of being spread across the route handlers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BookSchema(BaseModel):
    index: int
    name: str
    text: str
    picks: dict[str, list[str]] = Field(default_factory=dict)
    cache_path: str | None = None
    rating: dict | None = None


class TimingsSchema(BaseModel):
    """Per-phase seconds, so a client can show what a run cost."""

    phases: dict[str, float] = Field(default_factory=dict)
    total_seconds: float | None = None
    unaccounted_seconds: float | None = None


class GenerationSchema(BaseModel):
    scenario: str
    answer: str
    books: list[BookSchema] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    from_cache: bool = False
    model: str | None = None
    timings: TimingsSchema = Field(default_factory=TimingsSchema)
    # The stored run's id, so a client can rate a book without re-deriving it. Null when
    # the run was not persisted, which is the case with no character loaded.
    run_id: str | None = None

    @classmethod
    def from_generation(cls, generation) -> "GenerationSchema":
        timings = generation.timings or {}
        return cls(
            scenario=generation.scenario,
            run_id=generation.run_id,
            answer=generation.answer,
            books=[
                BookSchema(
                    index=book.index, name=book.name, text=book.text,
                    picks=book.picks or {}, cache_path=book.cache_path,
                    rating=book.rating,
                )
                for book in generation.books
            ],
            warnings=list(generation.warnings or []),
            from_cache=generation.from_cache,
            model=generation.model,
            timings=TimingsSchema(
                phases=timings.get("phases") or {},
                total_seconds=timings.get("total_seconds"),
                unaccounted_seconds=timings.get("unaccounted_seconds"),
            ),
        )


class AnswerSchema(BaseModel):
    """A reply to /c or /?.

    ``source`` is exposed because the client must be able to distinguish an exact sheet
    value from a model's reading of it. Presenting a guess with the same styling as a
    quoted field is the failure this field exists to prevent.
    """

    question: str
    answer: str
    source: str
    field_name: str | None = None
    citations: list[str] = Field(default_factory=list)
    from_cache: bool = False

    @classmethod
    def from_answer(cls, answer) -> "AnswerSchema":
        return cls(
            question=answer.question, answer=answer.answer, source=answer.source,
            field_name=answer.field_name, citations=list(answer.citations or []),
            from_cache=answer.from_cache,
        )


class SpellComponentsSchema(BaseModel):
    """A components line, expanded.

    `V, S, M (a bit of fleece)` assumes the reader already knows the rule, so the letters
    are sent with what they stand for. The material is sent exactly as the file wrote it -
    *which* material decides whether a component pouch covers the spell, and "a bit of
    fleece" is not something to summarise.
    """

    letters: list[str] = Field(default_factory=list)
    expanded: str
    material: str | None = None
    # A consumed material with a GP cost is why a spell can cost money to cast, which is a
    # material fact about a recommendation rather than a footnote.
    consumed: bool = False


class SpellDamageSchema(BaseModel):
    """One damage amount the spell states.

    ``dice`` is either a roll (``8d6``, ``10d6+40``) or a count of instances (``5x``, for
    "takes 5 Cold damage" from five separate hits). The two are not the same thing and are
    not rendered as though they were.
    """

    dice: str
    types: list[str] = Field(default_factory=list)
    # True when the text says the type is chosen at cast time - "3d8 damage of the chosen
    # type". Distinct from `types` being empty, which would just be unknown.
    chosen_type: bool = False


class SpellStatsSchema(BaseModel):
    """A spell's stat block, read back out of its own text.

    Every value is one the file already wrote; nothing here decides what a spell does. It
    exists because the file does not explain itself - `V` is Verbal only if you have
    memorised the Components rule, and the damage sits in the description's second
    paragraph where it is the most important number on the card.
    """

    casting_time: str
    # A ritual costs 10 minutes more to cast, which is a decision at the table.
    ritual: bool = False
    range: str | None = None
    components: SpellComponentsSchema | None = None
    duration: str | None = None
    # The most consequential thing about a spell for a caster who can hold only one.
    concentration: bool = False
    damage: list[SpellDamageSchema] = Field(default_factory=list)


class SpellSchema(BaseModel):
    """One spell, quoted verbatim from a vendored file.

    Read straight from the file rather than generated, so this is the one answer in the
    API that cannot be wrong: there is no model between the text and the caller. That is
    the point - a spell's damage dice and casting time are the numbers a recommendation is
    built on, and a paraphrase of them is worse than no answer.

    `source` says which file it came from. The SRD is preferred and is the 2024 authority;
    the retrieval corpus fills in the ~200 spells the SRD does not carry, which includes
    cantrips the app itself recommends. The two are not equally authoritative and the
    caller is told which it got.
    """

    name: str
    text: str
    url: str
    source: str
    # Null for anything that is not a spell. An Eldritch Invocation is quoted through this
    # same card and is a class feature, so it gets no stat block rather than an empty one.
    stats: SpellStatsSchema | None = None


class ScenarioRequest(BaseModel):
    scenario: str = Field(min_length=1, description="The encounter to plan for.")


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class RateRequest(BaseModel):
    score: int = Field(ge=1, le=5)
    book: str | None = Field(
        default=None,
        description="Book name fragment or index. Omit to rate every book in the run.",
    )
    notes: str | None = None
    outcome: str | None = None


class RunSummary(BaseModel):
    """One row of the history listing: a run, not a book.

    A book is ambiguous on its own, so the listing is keyed on the run - the scenario is
    what makes a book meaningful.
    """

    id: str
    scenario: str
    character: str | None = None
    level: int | None = None
    created_at: str | None = None
    model: str | None = None
    book_count: int = 0
    book_names: list[str] = Field(default_factory=list)
    timings: TimingsSchema = Field(default_factory=TimingsSchema)


class CharacterSchema(BaseModel):
    name: str
    sheet: dict
    text: str


class RunBooksSchema(BaseModel):
    """A stored run reopened for reading, with its ratings."""

    scenario: str
    created_at: str | None = None
    books: list[BookSchema] = Field(default_factory=list)
    # Carried so a book opened from history is rateable without a second lookup.
    run_id: str | None = None


class HealthSchema(BaseModel):
    status: str
    character: str | None = None
    model: str | None = None
    index_version: int
    cache_dir: str
