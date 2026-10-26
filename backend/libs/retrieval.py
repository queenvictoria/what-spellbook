"""Candidate collection and prompt-block rendering.

Two stages, deliberately separate:

1. **Eligibility** decides what is *legal* for the character (class, pact, subclass,
   level). This is a rules question and the scenario must never widen it.
2. **Ranking** uses the scenario to order an already-legal pool.

Book-of-Shadows lanes are fetched **exhaustively** from indexed metadata rather than by
similarity, because "pick 3" and "pick 2" are hard counts and a vector search cannot be
trusted to return all 48 cantrips. Levelled spells are excluded from the pool entirely:
a Warlock's prepared list does not change on a short rest, so offering them only
invited the model to mis-file them as picks.

Importing this module has no side effects and needs no network.
"""

from __future__ import annotations

import logging

from . import characters, config, spells

# --- RETRIEVAL ---
def dedupe_by_spell(documents):
    """Collapse the many chunks per spell into one hit, best chunk first.

    The index holds 1280 chunks for 544 spells, so a raw k of 30 was really only
    about 13 distinct spells - most of the context budget went to repeated text.
    """
    seen = {}
    for doc in documents:
        key = (doc.metadata.get("spell_name") or doc.metadata.get("filename")
               or doc.page_content[:64])
        if key not in seen:
            seen[key] = doc
    return list(seen.values())


def dedupe_spells(parsed_spells):
    """Drop duplicate spells from an exhaustive lane, preserving order.

    Each spell is stored as several chunks, so a metadata query returns one row per
    chunk and the same spell would otherwise be listed 2-12 times.
    """
    seen = set()
    unique = []
    for spell in parsed_spells:
        key = spell.name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(spell)
    return unique


def retrieve(db, query: str, where=None, k: int = config.RETRIEVAL_K):
    """Run one filtered similarity search, tolerating fakes and older stores.

    Minimal test doubles implement only ``as_retriever()``, so a missing
    ``similarity_search`` (AttributeError) falls back to the retriever path, as does a
    store that rejects the ``filter`` keyword (TypeError).
    """
    kwargs = {"k": k}
    if where:
        kwargs["filter"] = where
    try:
        return db.similarity_search(query, **kwargs)
    except (AttributeError, TypeError):
        return db.as_retriever(search_kwargs=kwargs).invoke(query)



def exhaustive_lane(db, where):
    """Return every spell matching ``where``, deduped.

    Prefers a direct metadata query: it is exact and needs no embedding call. Falls
    back to a similarity search so minimal test doubles still work.
    """
    if not where:
        return []
    try:
        payload = db.get(where=where, include=["metadatas"])
    except Exception as e:
        logging.debug(f"Metadata lane unavailable ({e}); using similarity search.")
        return dedupe_spells(
            spells.spell_from_metadata(d.metadata) for d in retrieve(db, "", where, config.RETRIEVAL_K)
        )
    return dedupe_spells(
        spells.spell_from_metadata(m) for m in payload.get("metadatas", [])
    )


def gather_spell_candidates(db, *, character: dict, query: str | None = None) -> dict:
    """Collect the legal Book of Shadows pool for a character.

    Only two things can go in the Book: cantrips and level 1 rituals. Both lanes are
    fetched **exhaustively** rather than by similarity, because "pick 3" and "pick 2"
    are hard counts and a similarity search cannot be trusted to surface every legal
    option.

    Crucially this returns *only* book-eligible spells. An earlier design also passed a
    list of every castable levelled spell for "synergy advice"; a local model then
    picked Misty Step and Daylight as book entries, because a flat spell list invites
    the model to treat it as pickable. Levelled spells add nothing here anyway - a
    Warlock's prepared list does not change on a short rest, so recommending one is not
    actionable.

    The scenario does not decide what is legal. It only ranks which legal candidates
    get their full text put in front of the model.
    """
    known = characters.known_spells(character)
    bucket = {"cantrips": [], "rituals": [], "ranked": []}

    bucket["cantrips"] = exhaustive_lane(db, spells.book_cantrip_filter(exclude_names=known))
    bucket["rituals"] = exhaustive_lane(db, spells.book_ritual_filter(exclude_names=known))

    if query:
        bucket["ranked"] = rank_book_candidates(
            db, query, exclude_names=known, cantrips=len(bucket["cantrips"]), rituals=len(bucket["rituals"])
        )

    logging.info(
        f"Legal pool: {len(bucket['cantrips'])} cantrip(s), "
        f"{len(bucket['rituals'])} level 1 ritual(s), "
        f"{len(bucket['ranked'])} scenario-ranked."
    )
    return bucket


def rank_book_candidates(db, query: str, *, exclude_names, cantrips: int, rituals: int):
    """Order book candidates by scenario relevance, for full-text selection only.

    Each lane is searched separately and the results sampled from both, so the model
    always sees ritual text as well as cantrip text - rituals are the less familiar
    half of the pick.
    """
    per_lane = max(1, config.FULL_TEXT_SPELLS // 2)
    ranked = []
    seen = set()

    for where in (
        spells.book_cantrip_filter(exclude_names=exclude_names),
        spells.book_ritual_filter(exclude_names=exclude_names),
    ):
        hits = dedupe_by_spell(retrieve(db, query, where, k=per_lane))
        for doc in hits[:per_lane]:
            key = doc.metadata.get("spell_name") or doc.metadata.get("filename")
            if key and key not in seen:
                seen.add(key)
                ranked.append(doc)
    return ranked


def format_pool(bucket: dict, slot_level: int | None, limit: int | None = None,
                 character: dict | None = None) -> str:
    """Render the book candidate pool handed to the model.

    Only two sections exist, both of them book-eligible. Levelled spells are
    deliberately absent: they cannot go in the book, and the prepared list does not
    change on a short rest, so offering them invited the model to mis-file them as
    picks.
    """
    sections = []

    if bucket.get("cantrips"):
        sections.append(
            "=== CANTRIP OPTIONS - the ONLY cantrips you may put in the book "
            f"(choose {spells.BOOK_CANTRIP_PICKS} per book) ===\n"
            f"{spells.describe_pool(bucket['cantrips'])}"
        )
    if bucket.get("rituals"):
        sections.append(
            "=== LEVEL 1 RITUAL OPTIONS - the ONLY rituals you may put in the book "
            f"(choose {spells.BOOK_RITUAL_PICKS} per book) ===\n"
            f"{spells.describe_pool(bucket['rituals'])}"
        )

    # If similarity ranking ran, note which options the scenario matched best. This is
    # a hint only - every listed spell remains legal.
    ranked = [spells.spell_from_metadata(d.metadata) for d in bucket.get("ranked", [])]
    if ranked and limit:
        rendered = "\n".join(spells.describe_pool(ranked).splitlines()[:limit])
        sections.append(
            "=== SCENARIO-MATCHED OPTIONS (a hint for ranking, still legal) ===\n"
            f"{rendered}"
        )

    if not sections:
        return "(no spells matched the eligibility filter)"
    if slot_level:
        sections.insert(0, f"All of this character's spell slots are level {slot_level}.")

    already = format_already_have(character)
    if already:
        sections.append(already)
    return "\n\n".join(sections)


# Human-readable labels for the per-source breakdown in the prompt. Kept next to the
# field list they annotate so the two cannot drift apart.
KNOWN_SOURCE_LABELS = {
    "Known/Prepared Base Spells": "Warlock picks",
    "Always Prepared Spells": "always prepared (patron, species or subclass)",
    "Cantrips From Other Sources": "from species, background or feats",
    "Free Casts Per Long Rest": "free casts per long rest",
}


def format_already_have(character: dict | None) -> str:
    """Spell out what the character already has, and what the book already holds.

    The sheet spreads this across several fields, so the model has to reconstruct it
    to make a sensible pick - and left to itself it spends book picks on spells the
    character already always has. Stating it once, as a flat list, makes the 'do not
    pick these' rule checkable instead of inferable.
    """
    if not character:
        return ""

    known = characters.known_spells(character)
    current = characters.current_book_spells(character)
    sources = [
        (label, characters.split_names(character.get(field)))
        for field, label in KNOWN_SOURCE_LABELS.items()
        if characters.split_names(character.get(field))
    ]
    if not known and not sources:
        return ""

    lines = [
        "=== ALREADY AVAILABLE - do NOT choose these as book picks ===",
        "The character already has these prepared or always available "
        "(including from species, background and feats):",
    ]
    lines.extend(f"  - {name}" for name in known)
    lines.extend(f"  ({label}: {', '.join(names)})" for label, names in sources)

    if current:
        lines.append("The book CURRENTLY holds: " + ", ".join(current) + ".")
        lines.append(
            "Those are still legal picks - the book is conjured fresh each rest - but "
            "only re-pick one if it genuinely remains the best choice for this scenario."
        )
    return "\n".join(lines)


def format_full_text(bucket: dict, limit: int = config.FULL_TEXT_SPELLS) -> str:
    """Render full page text for the scenario-ranked candidates."""
    blocks = []
    for doc in list(bucket.get("ranked", []))[:limit]:
        meta = doc.metadata
        header = f"[{meta.get('spell_name') or meta.get('filename')} | level {meta.get('level')}]"
        blocks.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)


