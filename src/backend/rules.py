"""Answer rules questions from the 2024 SRD, fetched once and cached.

The rules text lives at 5e24srd.com. Two things make this more than a wrapper around
``httpx.get``:

* **Edition.** This project is 2024-only. ``5thsrd.org`` serves the 2014 SRD and ranks
  well for "5e SRD" searches, so it is explicitly refused rather than silently used - a
  2014 answer would contradict the 2024 context files the prompts are built on.
* **Caching.** A rules answer is stable, so the fetched text and the model's answer are
  both stored under ``.cache/rules/`` keyed by the normalised question. Asking "what is
  a short rest?" twice must cost one fetch and one model call, not two.

The cache stores the *source text* alongside the answer, because an answer about a rule
is only checkable if the passage it came from is kept with it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from . import config

# The 2024 SRD. Only hosts on this list may be fetched from; see ``check_host``.
RULES_HOST = "5e24srd.com"
RULES_INDEX = f"https://{RULES_HOST}/"

# Section indexes. Each lists its own subpages, and the subpages carry the actual rule
# text - the index pages themselves are navigation only (~300 chars). Crawling these
# rather than hard-coding every page keeps the lookup working if the site adds or
# renames a rule, and avoids guessing URLs like /rules/ that 403.
SECTION_INDEXES = (
    f"https://{RULES_HOST}/playing-the-game/index.html",
    f"https://{RULES_HOST}/character-creation/index.html",
    f"https://{RULES_HOST}/equipment/index.html",
    f"https://{RULES_HOST}/spells/index.html",
    f"https://{RULES_HOST}/classes/index.html",
)

# Pages that are known homes for the rules a player asks about, tried first so the
# common case costs one fetch instead of a crawl.
PREFERRED_PAGES = (
    f"https://{RULES_HOST}/playing-the-game/exploration.html",
    f"https://{RULES_HOST}/playing-the-game/combat.html",
    f"https://{RULES_HOST}/playing-the-game/d20-tests.html",
    f"https://{RULES_HOST}/playing-the-game/actions.html",
    f"https://{RULES_HOST}/playing-the-game/damage-and-healing.html",
    f"https://{RULES_HOST}/playing-the-game/rhythm-of-play.html",
)

# Hosts that must never be used, with the reason, so the refusal is self-documenting.
BANNED_HOSTS = {
    "5thsrd.org": "serves the 2014 SRD (5.1), not 2024; its own banner says so",
    "www.5thsrd.org": "serves the 2014 SRD (5.1), not 2024; its own banner says so",
}

_CACHE_SUBDIR = "rules"
_QUESTION_HASH_LENGTH = 12

# Long enough to clear a nav bar, short enough to be a real answer's neighbourhood.
MIN_USEFUL_CHARS = 400


class RulesUnavailable(RuntimeError):
    """Raised when a rules page cannot be fetched or yields no usable text."""


def normalise(question: str) -> str:
    """Fold a question so trivial rewording hits the same cache entry."""
    return " ".join(str(question).lower().split()).strip(" ?.!")


def question_fingerprint(question: str) -> str:
    """Short stable hash of a normalised question, used as the cache filename."""
    digest = hashlib.sha256(normalise(question).encode("utf-8")).hexdigest()
    return digest[:_QUESTION_HASH_LENGTH]


def slug(question: str, *, max_length: int = 48) -> str:
    """Readable part of the cache filename, so the directory can be browsed."""
    words = re.findall(r"[a-z0-9]+", normalise(question))
    return ("-".join(words)[:max_length].strip("-")) or "question"


def _cache_dir(cache_dir=None) -> Path:
    """``.cache/rules/`` - rules answers are cached beside the generated books."""
    root = Path(cache_dir) if cache_dir is not None else config.CACHE_DIR_PATH
    return root / _CACHE_SUBDIR


def entry_path(question: str, cache_dir=None) -> Path:
    """Cache file for a question: readable slug plus a short hash."""
    return cache_dir_path(question, cache_dir)


def cache_dir_path(question: str, cache_dir=None) -> Path:
    return _cache_dir(cache_dir) / f"{slug(question)}-{question_fingerprint(question)}.json"


def check_host(url: str) -> None:
    """Refuse a non-2024 host before any request is made."""
    host = re.sub(r"^https?://", "", str(url)).split("/")[0].lower()
    host = host.split(":")[0]
    if host in BANNED_HOSTS:
        raise RulesUnavailable(
            f"{host} is a 2014 source ({BANNED_HOSTS[host]}); this project is 2024 only."
        )
    if host and host != RULES_HOST and not host.endswith("." + RULES_HOST):
        raise RulesUnavailable(f"{host} is not a permitted rules source ({RULES_HOST}).")


def html_to_text(html: str) -> str:
    """Flatten a rules page to readable text, marking headings.

    Headings are kept with a ``##`` sentinel rather than discarded, because a rule is
    defined *under its own heading*. That is the difference between the section titled
    "Cover" and a sentence that merely says "an object that covers the whole target",
    and without it the matcher cannot tell a rule from a mention.

    Deliberately dependency-free: a rules page is simple markup and adding a parser for
    it would be a large dependency for one function. Script, style and nav bodies are
    dropped first, because their contents are not prose.
    """
    text = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ",
                  html, flags=re.S | re.I)
    # Mark headings before the generic tag strip, so the marker survives.
    text = re.sub(r"<h[1-6][^>]*>\s*(.*?)\s*</h[1-6]>", r"\n## \1\n", text,
                  flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# Words that carry no retrieval signal. Without this, "what is a short rest" scores a
# passage highly for containing "is" and "a", and a passage about *when time is short*
# outranks one that actually mentions resting. Question-framing verbs ("how does X
# work", "what does X mean") are included because they name the question, not the rule.
_STOPWORDS = frozenset("""
a about an and are as at be been being by can could did do does doing done for from get
gets got had has have having how i if in into is it its just like make makes me mean
means more most much must my need no not of on or other our out over own said same
should so some such than that the their them then there these they this those to too
up use used uses using very was way were what when where whether which while who whom
why will with work works would you your
""".split())

# A passage must contain this fraction of the question's meaningful terms before it is
# offered as an answer. Deliberately strict: an irrelevant passage presented as the
# rule is worse than admitting the rule was not found, because it reads authoritative.
_COVERAGE_THRESHOLD = 0.6


def _terms(question: str) -> set[str]:
    """Meaningful terms in a question, folded so grammatical variants still match.

    Suffix folding rather than a stemmer: "grappling" must match "Grappled", and
    "conditions" must match "condition". Without it, "how does grappling work" found only
    the string "Grappling Hook" in an equipment list, because the rulebook says
    "Grappled" - so the answer came from a tool description.

    Only the stem is emitted, not the stem plus the original. Emitting both inflated the
    term set ("grappling" produced ``grappl``, ``grappling`` *and* a bogus ``grappll``),
    which then lowered coverage on the page that actually had the rule and let a weaker
    page win.
    """
    words = {w for w in re.findall(r"[a-z]{3,}", normalise(question))}
    words -= _STOPWORDS
    folded = set()
    for word in words:
        if word.endswith("s") and len(word) > 4:          # conditions -> condition
            word = word[:-1]
        if word.endswith("ing") and len(word) > 6:        # grappling  -> grappl
            word = word[:-3]
        elif word.endswith("ed") and len(word) > 5:       # grappled   -> grappl
            word = word[:-2]
        folded.add(word)
    return folded


# Text the SRD uses to point elsewhere. When a passage says "see the Rules Glossary"
# and the glossary is not part of the SRD, the passage is a cross-reference, not
# content - which is how a travel-pace sentence about mounts became an "answer" about
# short rests.
_CROSS_REFERENCE = re.compile(
    r"see\s+[“\"']?(rules glossary|equipment|combat|chapter|\w+ rules)", re.I
)

# Sections whose headings are navigation or lists rather than rule definitions. A
# price or a "Hook"/"Kit" suffix marks an equipment entry, which is how "Grappling Hook
# (2 GP)" was offered as the answer to how grappling works.
_NON_RULE_HEADINGS = re.compile(
    r"\b(tools?|table|example|sample|trinkets?|equipment|gear|armor|weapons?|coins?|"
    r"expenses|lodging|hirelings?|mounts?|vehicles?|crafting|lifestyle|hook|kit|"
    r"focus|supplies|list)\b"
    r"|\b\d+\s*(gp|sp|cp|lb)\b",
    re.I,
)


def _sections(text: str) -> list[tuple[str, str]]:
    """Split marked-up page text into ``(heading, body)`` pairs.

    Content before the first heading is kept under an empty heading, because plenty of a
    rules page's introduction is real rule text.
    """
    parts = re.split(r"^##\s*(.*)$", text, flags=re.MULTILINE)
    # re.split with a capture group yields [lead, head1, body1, head2, body2, ...].
    sections = []
    lead = parts[0].strip()
    if lead:
        sections.append(("", lead))
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body:
            sections.append((heading, body))
    return sections


def find_passages(text: str, question: str, *, limit: int = 3) -> list[str]:
    """The page sections most likely to answer ``question``, best first.

    Matching works on *sections*, not loose paragraphs, and a section whose heading
    contains the question's terms outranks one that merely mentions them in passing. A
    rule is defined under its own heading ("Cover", "Grappled"), so the heading is the
    strongest available signal - and its absence is what let "Grappling Hook" in an
    equipment list and a travel-pace sentence about mounts beat the real rule.

    Returns an empty list when nothing qualifies. That is a real outcome, not a failure:
    much of the 2024 rulebook is not in the SRD, and the caller reports the gap rather
    than presenting an unrelated passage as the rule.
    """
    terms = _terms(question)
    if not terms:
        return []

    scored = []
    for position, (heading, body) in enumerate(_sections(text)):
        heading_lower = heading.lower()
        body_lower = body.lower()

        # A heading that is really a list or an equipment table is never the rule.
        if heading and _NON_RULE_HEADINGS.search(heading):
            continue

        in_heading = [t for t in terms if re.search(rf"\b{re.escape(t)}", heading_lower)]
        in_body = [t for t in terms if re.search(rf"\b{re.escape(t)}", body_lower)]
        if not in_body and not in_heading:
            continue

        coverage = len(set(in_heading) | set(in_body)) / len(terms)
        # A heading hit is worth far more than a body hit: it means this section *is*
        # the rule rather than prose that happens to use the word.
        heading_bonus = 2.0 if in_heading else 0.0
        score = heading_bonus + coverage * (1 + 0.1 * min(len(in_body), 5))
        # Long sections are diluted: a huge appendix mentioning the term once is less
        # useful than a short dedicated rule.
        score /= 1 + len(body) / 2500
        # A cross-reference is not content. Without this the strongest-looking match for
        # "short rest" was a travel-pace sentence pointing at the Rules Glossary, which
        # the SRD does not contain.
        if _CROSS_REFERENCE.search(body) and not in_heading:
            score /= 3.0
        scored.append((score, position, heading, body))

    if not scored:
        return []

    # Require the best section's *heading* to be about the question. The SRD defines a
    # rule under a heading that names it ("Cover", "Hiding", "Dropping Prone"), so a
    # section that merely mentions the terms in passing is not the rule - it is how
    # "Hit Points" became an answer about short rests. Refusing is the honest outcome:
    # much of the 2024 rulebook (rests, the Rules Glossary, most conditions) is not in
    # the SRD, and a plausible-looking paragraph is worse than saying so.
    best = max(scored, key=lambda s: s[0])
    if not best[2]:
        return []
    if not any(re.search(rf"\b{re.escape(t)}", best[2].lower()) for t in terms):
        return []

    scored.sort(key=lambda s: (-s[0], s[1]))
    out = []
    for _score, _pos, heading, body in scored[:limit]:
        label = f"## {heading}\n" if heading else ""
        out.append(f"{label}{body}")
    return out


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_cached(question: str, cache_dir=None) -> dict | None:
    """A previously answered rules question, or None."""
    entry = _read(entry_path(question, cache_dir))
    if not entry or not entry.get("answer"):
        return None
    if entry.get("source") != RULES_HOST:
        # A cached answer from a different (older) source is not usable.
        return None
    return entry


def save_cached(question: str, answer: str, *, passages: list[str], url: str,
                cache_dir=None) -> Path:
    """Store a rules answer with its source text and URL. Never raises."""
    from datetime import datetime, timezone

    path = entry_path(question, cache_dir)
    entry = {
        "question": question.strip(),
        "normalised": normalise(question),
        "answer": answer,
        "passages": passages,
        "url": url,
        "source": RULES_HOST,
        "answered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logging.warning(f"Could not cache the rules answer ({e}).")
    return path


def fetch_page(url: str, *, timeout: float = 20.0) -> str:
    """Fetch a rules page as text. Refuses a non-2024 host before connecting."""
    check_host(url)
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise RulesUnavailable(f"httpx is required for rules lookups: {e}") from e

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": "what-spellbook/1.0"})
    except Exception as e:
        raise RulesUnavailable(f"Could not reach {url} ({type(e).__name__}: {e})") from e

    if response.status_code != 200:
        raise RulesUnavailable(f"{url} returned HTTP {response.status_code}.")

    text = html_to_text(response.text)
    if len(text) < MIN_USEFUL_CHARS:
        raise RulesUnavailable(
            f"{url} produced only {len(text)} characters of text; the page layout may "
            "have changed."
        )
    return text


def section_pages(index_url: str, *, timeout: float = 20.0) -> list[str]:
    """Subpage URLs listed by a section index.

    Resolves the index's relative links against its own directory, skipping the
    cross-section navigation links - those point at ``../other-section/index.html``,
    which would make each section crawl the whole site.
    """
    import httpx

    check_host(index_url)
    try:
        response = httpx.get(index_url, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": "what-spellbook/1.0"})
        response.raise_for_status()
    except Exception as e:
        logging.warning(f"Could not read the index {index_url} ({type(e).__name__}).")
        return []

    base = index_url.rsplit("/", 1)[0]
    pages = []
    for href in re.findall(r'href="([^"#?]+\.html)"', response.text):
        if href.startswith(("http://", "https://")) or href.startswith(".."):
            continue
        pages.append(f"{base}/{href}")
    return list(dict.fromkeys(pages))


def candidate_pages(*, timeout: float = 20.0) -> list[str]:
    """Every page worth searching, known-good ones first.

    Discovery is lazy: the preferred pages are tried before any index is crawled, so
    the common question ("what is a short rest?") costs one request, and the crawl is
    only paid for when the preferred pages miss.
    """
    pages = list(PREFERRED_PAGES)
    for index in SECTION_INDEXES:
        pages.extend(section_pages(index, timeout=timeout))
    return list(dict.fromkeys(pages))


def gather(question: str, *, urls=None, cache_dir=None, timeout: float = 20.0,
           search_all: bool = True) -> dict:
    """Retrieve the rules passages for a question, from cache when possible.

    Returns ``{"passages", "url", "text", "from_cache"}``. Raises ``RulesUnavailable``
    when nothing can be fetched, so the caller can say so rather than answering from
    model recall and presenting it as sourced.
    """
    cached = load_cached(question, cache_dir)
    if cached:
        return {
            "passages": cached.get("passages") or [],
            "url": cached.get("url", RULES_INDEX),
            "text": "\n\n".join(cached.get("passages") or []),
            "from_cache": True,
        }

    if urls is not None:
        candidates = urls
    else:
        candidates = candidate_pages(timeout=timeout) if search_all else list(PREFERRED_PAGES)

    fallback_url = candidates[0] if candidates else RULES_INDEX
    for url in candidates:
        try:
            text = fetch_page(url, timeout=timeout)
        except RulesUnavailable as e:
            logging.debug(f"Rules fetch failed for {url}: {e}")
            continue
        found = find_passages(text, question)
        if found:
            return {"passages": found, "url": url, "text": "\n\n".join(found),
                    "from_cache": False}

    raise RulesUnavailable(
        f"Could not find anything about '{question}' in the {RULES_HOST} rules."
    )
