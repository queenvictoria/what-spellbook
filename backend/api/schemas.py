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
    # The book's prose only. A run stored before the delimited format was introduced has
    # its title and pick list still inside this text, because the old format had nowhere
    # else to put them; `picks` and `name` are authoritative either way.
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
    # Reasoning that applies to every book, and the pairing summary. Both used to be
    # inside the last book's text, which is why they are separate fields now.
    preamble: str = ""
    pairings: str = ""
    warnings: list[str] = Field(default_factory=list)
    from_cache: bool = False
    model: str | None = None
    timings: TimingsSchema = Field(default_factory=TimingsSchema)
    # The stored run's id, so a client can rate a book without re-deriving it. Null when
    # the run was not persisted, which is the case with no character loaded.
    run_id: str | None = None
    # The conversation a refinement belongs to, so a client can continue it or read it
    # back. Null for a fresh generation, which is not a conversation.
    thread_id: str | None = None

    @classmethod
    def from_generation(cls, generation) -> "GenerationSchema":
        timings = generation.timings or {}
        return cls(
            scenario=generation.scenario,
            run_id=generation.run_id,
            thread_id=getattr(generation, "thread_id", None),
            answer=generation.answer,
            preamble=generation.preamble,
            pairings=generation.pairings,
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

    ``rules`` is a rule quoted from the 2024 SRD; ``rules-inferred`` is an answer
    *interpreted* from related SRD text when no heading names the question. The two are
    kept apart for the same reason: an interpretation must not look like a quotation.
    """

    question: str
    answer: str
    source: str
    field_name: str | None = None
    citations: list[str] = Field(default_factory=list)
    from_cache: bool = False
    # The documents this answer was given, by name. Exposed because an answer that reports
    # the SRD does not cover a spell reads very differently once the reader can see the
    # spell was never attached - and that difference is invisible from the text alone.
    attachments: list[str] = Field(default_factory=list)
    # The conversation this answer belongs to. A client passes it back to ask a follow-up
    # in context, and uses it to read the exchange again later.
    thread_id: str | None = None

    @classmethod
    def from_answer(cls, answer) -> "AnswerSchema":
        return cls(
            question=answer.question, answer=answer.answer, source=answer.source,
            field_name=answer.field_name, citations=list(answer.citations or []),
            from_cache=answer.from_cache, attachments=list(answer.attachments or []),
            thread_id=getattr(answer, "thread_id", None),
        )


class ConversationTurnSchema(BaseModel):
    """One question and its answer, with the provenance a reader needs to trust it."""

    question: str
    answer: str
    source: str
    asked_at: str | None = None
    field_name: str | None = None
    citations: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    from_cache: bool = False
    model: str | None = None

    @classmethod
    def from_turn(cls, turn) -> "ConversationTurnSchema":
        return cls(
            question=turn.question, answer=turn.answer, source=turn.source,
            asked_at=turn.asked_at, field_name=turn.field_name,
            citations=list(turn.citations or []),
            attachments=list(turn.attachments or []),
            from_cache=turn.from_cache, model=turn.model,
        )


class ConversationSummary(BaseModel):
    """One row of the conversation listing: a thread, not a single answer.

    A follow-up is only meaningful beside the question it followed, so the listing is
    keyed on the thread and the opening question is what names it.
    """

    id: str
    kind: str
    opening: str
    character: str | None = None
    run_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    turn_count: int = 0
    # The most recent answer, so a listing can be scanned without opening every thread.
    last_answer: str = ""

    @classmethod
    def from_conversation(cls, conversation) -> "ConversationSummary":
        return cls(
            id=conversation.id, kind=conversation.kind, opening=conversation.opening,
            character=conversation.character, run_id=conversation.run_id,
            created_at=conversation.created_at, updated_at=conversation.updated_at,
            turn_count=len(conversation.turns),
            last_answer=conversation.last_answer,
        )


class ConversationSchema(BaseModel):
    """A whole thread, every turn in order."""

    id: str
    kind: str
    opening: str
    character: str | None = None
    run_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    turns: list[ConversationTurnSchema] = Field(default_factory=list)

    @classmethod
    def from_conversation(cls, conversation) -> "ConversationSchema":
        return cls(
            id=conversation.id, kind=conversation.kind, opening=conversation.opening,
            character=conversation.character, run_id=conversation.run_id,
            created_at=conversation.created_at, updated_at=conversation.updated_at,
            turns=[ConversationTurnSchema.from_turn(t) for t in conversation.turns],
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
    # What the spell does at the *loaded character's* level, e.g. "2 beams (L5)". Null when
    # the spell does not scale with level, when no character is loaded, or when the
    # character is below the first level the spell states.
    #
    # The value is read out of the spell's own text, so it is a rule rather than a
    # recollection - but it is *applied* to a character, which is why it is a separate
    # field from `text` and not folded into it. A reader must be able to tell the spell's
    # words from this app's reading of them.
    scaling: str | None = None


class ScenarioRequest(BaseModel):
    scenario: str = Field(min_length=1, description="The encounter to plan for.")


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    # Continue an existing conversation. Omitted, the question opens one - or joins the
    # thread it already opened, since a thread is keyed on its opening question.
    thread_id: str | None = None


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
    # The same two fields `GenerationSchema` carries, so a run reopened from history renders
    # exactly as it did when it was generated.
    preamble: str = ""
    pairings: str = ""
    # Carried so a book opened from history is rateable without a second lookup.
    run_id: str | None = None


class HealthSchema(BaseModel):
    status: str
    character: str | None = None
    model: str | None = None
    index_version: int
    cache_dir: str


class SearchHitSchema(BaseModel):
    """One distinct spell a search returned, with the chunk that matched it.

    Distinct spells, not chunks: the index holds ~1280 chunks for 544 spells, so a raw
    result list would show the same spell two or three times and read as a duplicate bug.
    """

    name: str
    level: int | None = None
    # "Cantrip" / "Level 3" / "Not a spell", computed server-side so every surface writes a
    # level the same way - and so the index's -1 marker for a magic item never leaks out.
    level_label: str
    school: str | None = None
    classes: list[str] = Field(default_factory=list)
    ritual: bool = False
    is_spell: bool = True
    filename: str
    text: str
    # Which kind of indexed text this is: "spell", "item" or "srd". A client needs it to
    # tell a rule from a spell, because an SRD row has no school and a level of 0.
    doc_type: str = "spell"
    # For an SRD row, the document and heading it came from, so the hit can be opened as a
    # rule rather than shown as an orphaned paragraph.
    document: str | None = None
    slug: str | None = None
    # How many of this spell's chunks matched, not how many it has.
    chunks: int = 1
    # Chroma's distance for the best chunk, or null when the store cannot score. Lower is
    # closer; it is not a percentage and the scale depends on the embedding model.
    distance: float | None = None
    # How many of the query's words the matching chunks contain.
    terms_matched: int = 0


class SearchFacetSchema(BaseModel):
    value: str
    count: int


class SearchLevelFacetSchema(BaseModel):
    level: int
    label: str
    count: int


class SearchFacetsSchema(BaseModel):
    """What the index holds, so a client can offer filter values that actually exist."""

    classes: list[SearchFacetSchema] = Field(default_factory=list)
    schools: list[SearchFacetSchema] = Field(default_factory=list)
    levels: list[SearchLevelFacetSchema] = Field(default_factory=list)
    rituals: int = 0
    spells: int = 0
    chunks: int = 0
    # How many rows of each kind the collection holds, so the doc-type filter can be offered
    # with real counts.
    doc_types: list[SearchFacetSchema] = Field(default_factory=list)


class SearchResultSchema(BaseModel):
    """One search over the vector index.

    ``where`` is the Chroma clause actually sent, echoed back because a filter that
    silently matches nothing is the commonest failure here and the clause is the fastest
    way to see why. ``total_matching`` counts the distinct spells the *criteria* admit -
    filters always, plus the words in text mode - so it says whether a filter is too
    narrow. A vector search has no relevance threshold, so it cannot say how many spells
    are relevant.
    """

    query: str
    mode: str
    limit: int
    offset: int = 0
    hits: list[SearchHitSchema] = Field(default_factory=list)
    total_matching: int = 0
    elapsed_ms: float = 0.0
    where: dict | None = None
    filters: dict = Field(default_factory=dict)
    # Set when the result needs explaining: a filter that cannot match, an AND that found
    # nothing, or a candidate cap that truncated the ranking.
    note: str | None = None

    @classmethod
    def from_result(cls, result) -> "SearchResultSchema":
        return cls(
            query=result.query, mode=result.mode, limit=result.limit,
            offset=result.offset, total_matching=result.total_matching,
            elapsed_ms=result.elapsed_ms, where=result.where, filters=result.filters,
            note=result.note,
            hits=[
                SearchHitSchema(
                    name=hit.name, level=hit.level, level_label=hit.level_label,
                    school=hit.school, classes=list(hit.classes), ritual=hit.ritual,
                    is_spell=hit.is_spell, filename=hit.filename, text=hit.text,
                    chunks=hit.chunks, distance=hit.distance,
                    terms_matched=hit.terms_matched, doc_type=hit.doc_type,
                    document=hit.document, slug=hit.slug,
                )
                for hit in result.hits
            ],
        )


class SearchFacetsResponse(BaseModel):
    """The filter vocabulary, plus the index version it describes.

    The version is carried because the facets are read from the index, not from config: a
    client caching them needs to know when a rebuild has changed what exists.
    """

    index_version: int
    facets: SearchFacetsSchema


class SrdHeadingSchema(BaseModel):
    """One heading in a vendored SRD file, nested under its parent.

    ``slug`` is the anchor a client asks for, and it is de-duplicated within its document:
    the SRD repeats headings - ``classes.md`` has six ``Level 1: Spellcasting`` sections,
    one per class - so a slug derived from the text alone would collide and every link
    after the first would open the wrong section.
    """

    text: str
    level: int
    slug: str
    children: list["SrdHeadingSchema"] = Field(default_factory=list)


class SrdDocumentSchema(BaseModel):
    """One vendored SRD file, as a table of contents.

    The tree is sent without the text. The seven files are ~880KB of Markdown between
    them, and a client that only wants to draw a list of links should not pay for the
    rulebook - so the text is fetched per section, on the click that needs it.
    """

    name: str
    title: str
    path: str
    headings: list[SrdHeadingSchema] = Field(default_factory=list)

    @classmethod
    def from_document(cls, document) -> "SrdDocumentSchema":
        return cls(
            name=document.name,
            title=document.title,
            path=document.path,
            headings=[_heading(h) for h in document.headings],
        )


def _heading(heading) -> SrdHeadingSchema:
    return SrdHeadingSchema(
        text=heading.text,
        level=heading.level,
        slug=heading.slug,
        children=[_heading(child) for child in heading.children],
    )


class SrdCrumbSchema(BaseModel):
    """One step in a section's ancestry, for a breadcrumb.

    ``slug`` is what a click asks for, so a crumb is a link to the parent rule rather than
    just a label. The document's own root heading is included as the first crumb, which is
    why a section's trail starts at the file rather than at its first real subdivision.
    """

    text: str
    slug: str
    level: int


class SrdSectionSchema(BaseModel):
    """One heading's own text, as renderable Markdown.

    ``text`` includes the heading line, so the fragment reads as a document rather than a
    body with no title. ``path`` is the repo-relative file, shown so a reader can find the
    rule in the vendored corpus themselves.

    ``ancestors`` is the chain of headings above this one, outermost first, excluding the
    heading itself. It is sent rather than left for the client to derive because the client
    only holds the table of contents, and walking it to find a parent would mean a second
    lookup for something the server already knows.
    """

    document: str
    title: str
    heading: str
    slug: str
    path: str
    text: str
    source: str = "vendored-srd-5.2.1"
    ancestors: list[SrdCrumbSchema] = Field(default_factory=list)

    @classmethod
    def from_section(cls, section) -> "SrdSectionSchema":
        return cls(
            document=section.document.name,
            title=section.document.title,
            heading=section.heading.text,
            slug=section.heading.slug,
            path=section.document.path,
            text=section.text,
            ancestors=[
                SrdCrumbSchema(text=h.text, slug=h.slug, level=h.level)
                for h in section.ancestors
            ],
        )
