import os
import cmd
import re
import shutil
import signal
import time
import sys
import argparse
from pathlib import Path
import threading
try:
    import readline
except ImportError:  # Windows has no readline; cmd merely loses TAB completion there.
    readline = None
import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Modern LangChain ecosystem imports
from dotenv import load_dotenv
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from chromadb.api.shared_system_client import SharedSystemClient

import logging

import prompts
import spells

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Pull OPENROUTER_API_KEY (and friends) out of the untracked .env file next to this script.
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE)

# --- CONFIGURATION ---
DOCS_DIR = "./data/reddit-spence_post/Spells"
DB_DIR = "./data/chroma_db"

# Bump when the shape or meaning of the stored metadata changes, so a stale index is
# rebuilt instead of silently answering filters with old fields.
INDEX_VERSION = 3

# How many candidate spells to hand the model, and how many get full text. k is per
# filtered query lane; dedupe collapses the many chunks each spell is split into.
RETRIEVAL_K = 60
FULL_TEXT_SPELLS = 12
CONTEXT_DIR = "context"

# Character sheets live as YAML files in this directory; CHARACTER env var picks one.
CHARACTERS_DIR = "./data/characters"
DEFAULT_CHARACTER = "lois"

# Primary reasoning model: DeepSeek V4.1 Flash over OpenRouter's OpenAI-compatible API.
# Local Ollama (same model the embeddings use) remains the offline fallback.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OLLAMA_MODEL = "qwen3.5:4b"
EMBEDDING_MODEL = "nomic-embed-text"

# The embeddings client is built lazily so importing this module never talks to Ollama.
_embeddings = None


def get_embeddings():
    """Return the process-wide embeddings client, creating it on first use."""
    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    return _embeddings


# --- DIRECTORY SANITY CHECK & DB RESET ---
def _index_metadata(db_dir=None):
    """Return the stored index metadata mapping, or {} when unreadable.

    Opening a Chroma store creates the directory as a side effect, so callers must
    check for the sqlite file first.
    """
    db_dir = db_dir or DB_DIR
    try:
        db = Chroma(persist_directory=db_dir, embedding_function=get_embeddings())
        collection = db._collection
        return dict(collection.metadata or {})
    except Exception:
        logging.debug(f"Could not read index metadata at {db_dir}.", exc_info=True)
        return {}


def _db_is_valid(db_dir: str) -> bool:
    """Load the persisted Chroma index and confirm it holds data of the current shape.

    Returns False unless the collection opens cleanly, contains embeddings, and was
    written at the current ``INDEX_VERSION``. The version check matters because the
    metadata fields used for filtering were added later; an older index would make
    every metadata filter silently return nothing.

    This replaces the previous broken guard that wiped any existing directory.
    """
    # Opening a Chroma store creates the directory and sqlite file as a side effect,
    # so bail out early when there is no index on disk yet.
    if not (Path(db_dir) / "chroma.sqlite3").exists():
        return False

    try:
        db = Chroma(persist_directory=db_dir, embedding_function=get_embeddings())
        payload = db.get(include=["embeddings"])
        # `embeddings` comes back as a numpy array, whose truth value is ambiguous -
        # `not`/`bool()` on it raises, so length is the only safe emptiness test.
        if payload is None or len(payload["embeddings"]) == 0:
            return False
    except Exception as e:
        logging.warning(f"Could not read index at {db_dir} ({e}); treating as unusable.")
        return False

    version = _index_metadata(db_dir).get("index_version")
    if version != INDEX_VERSION:
        logging.info(
            f"Index metadata version {version!r} does not match {INDEX_VERSION}; rebuilding."
        )
        return False
    return True


def _reset_db(db_dir: str) -> None:
    """Delete the persisted index so it can be rebuilt from scratch.

    Chroma caches its sqlite connection per persist path. If we delete the
    directory while that cached client is still alive, the rebuild reuses the
    stale handle and fails with "attempt to write a readonly database".
    Dropping the cache first forces a fresh client against the new directory.
    """
    SharedSystemClient.clear_system_cache()
    if os.path.exists(db_dir):
        shutil.rmtree(db_dir)


def _build_index(docs_path: Path, db_dir: str):
    """Read every spell markdown file, chunk it, and persist a fresh Chroma index."""
    md_files = list(docs_path.rglob("*.md"))
    logging.info(f"Discovered {len(md_files)} spell markdown files across subdirectories.")

    logging.info(f"Processing and vectorizing all {len(md_files)} files. This will take a moment...")
    documents = []

    for p in md_files:
        try:
            content = p.read_text(encoding="utf-8")
            logging.debug(f"Read file: {p}")

            # Parse level/school/class-list/ritual out of the page header so the
            # eligibility filters can run inside Chroma instead of in the prompt.
            parsed = spells.parse_spell(spells.prettify_name(p.stem), p.name, content)

            # Secure the spell name explicitly inside the document body text block
            secured_content = f"Spell Name: {parsed.name}\n\n{content}"

            documents.append(
                Document(page_content=secured_content, metadata=spells.build_metadata(parsed, str(p)))
            )
        except Exception as e:
            logging.error(f"Could not read file {p}: {e}")

    if not documents:
        logging.critical(f"No readable spell documents under {docs_path}.")
        exit(1)

    # Split using Markdown header tags matching your exact spell sheet structure
    headers_to_split_on = [("#", "Spell Name Header")]
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

    final_docs = []
    for doc in documents:
        header_splits = md_splitter.split_text(doc.page_content)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
        chunks = text_splitter.split_documents(header_splits)

        # Ensure metadata maps down accurately to each generated text chunk
        for chunk in chunks:
            chunk.metadata.update(doc.metadata)
        final_docs.extend(chunks)

    db = Chroma.from_documents(
        final_docs,
        get_embeddings(),
        persist_directory=db_dir,
        collection_metadata={"index_version": INDEX_VERSION, "hnsw:space": "l2"},
    )
    logging.info(f"Rebuild Complete: Indexed {len(final_docs)} total text chunks into ChromaDB.")
    return db


def ensure_db(docs_path=None, db_dir=None):
    """Return the vector index, rebuilding from source only when it is unusable.

    If the spell source directory is missing the persisted index is loaded as-is.
    A rebuild happens only when there are enough source files AND the index is
    absent or unreadable, so a merely-existing directory is never wiped.

    This runs from main() rather than at import time: importing this module must
    never scan, embed, or delete anything.
    """
    docs_path = Path(docs_path or DOCS_DIR)
    db_dir = db_dir or DB_DIR

    if not docs_path.exists():
        logging.critical(f"The directory '{docs_path}' does not exist. Check your path layout.")
        exit(1)

    md_files = list(docs_path.rglob("*.md"))
    if len(md_files) > 10 and not _db_is_valid(db_dir):
        logging.warning("Database reset triggered. Wiping corrupt/missing/unreadable index...")
        _reset_db(db_dir)
        return _build_index(docs_path, db_dir)

    logging.debug("Loading existing vector index from DB_DIR...")
    return Chroma(persist_directory=db_dir, embedding_function=get_embeddings())


# --- FILE WATCHING ---
class ChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        logging.info(f"File {event.src_path} has been modified.")
        # Trigger rebuild logic here

def _stop_observer(observer):
    """Stop the watchdog thread, tolerating an observer that never started."""
    if observer is None:
        return
    try:
        observer.stop()
        observer.join(timeout=5)
    except Exception as e:
        logging.warning(f"Could not stop the file watcher cleanly: {e}")


def start_watching(path, observer):
    """Run the filesystem watcher until the process is interrupted.

    Exceptions are swallowed here so a failure in this background thread never
    tears down the REPL running on the main thread.
    """
    try:
        event_handler = ChangeHandler()
        observer.schedule(event_handler, path, recursive=True)
        observer.start()

        # A plain sleep loop keeps the thread responsive to stop() without busy-waiting.
        while observer.is_alive():
            time.sleep(1)
    except Exception as e:
        logging.error(f"File watcher stopped unexpectedly: {e}")
    finally:
        _stop_observer(observer)


# The watcher starts only when main() runs, so importing this module has no side effects.
watch_thread = None


def get_observer():
    """Create a fresh watchdog Observer.

    Observer instances are single-use: watchdog raises RuntimeError on a second
    start(), so one is built per run rather than module import.
    """
    return Observer()

# --- LLM BACKEND SELECTION ---
def build_llm():
    """Prefer OpenRouter's DeepSeek V4.1 Flash, fall back to a local Ollama model.

    OpenRouter is only attempted when a key is present; any failure to construct
    the client (bad key format, missing dependency) drops us back to Ollama rather
    than aborting the session.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        try:
            llm = ChatOpenAI(
                model=OPENROUTER_MODEL,
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                temperature=0.3,
                max_retries=2,
                timeout=180,
            )
            logging.info(f"LLM backend: OpenRouter ({OPENROUTER_MODEL})")
            return llm
        except Exception as e:
            logging.warning(f"Could not initialise OpenRouter client ({e}); falling back to Ollama.")

    logging.info(f"LLM backend: Ollama ({OLLAMA_MODEL})")
    return OllamaLLM(model=OLLAMA_MODEL)


# --- CHARACTER SHEETS ---
def _format_character(data: dict) -> str:
    """Render a parsed character sheet as the plain-text block the prompt expects."""
    lines = []
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{str(key).replace('_', ' ').title()}: {value}")
    return "\n".join(lines)


def load_character_data(name: str) -> dict:
    """Load data/characters/<name>.yaml and return the parsed mapping.

    Name can be a bare stem (or 'data/characters/x.yaml') supplied by --character
    or the CHARACTER env var. Exits with a clear message rather than a traceback.
    """
    stem = Path(name).stem
    path = Path(CHARACTERS_DIR) / f"{stem}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in Path(CHARACTERS_DIR).glob("*.yaml"))
        logging.critical(
            f"Character sheet '{path}' not found. Available: {', '.join(available) or 'none'}."
        )
        exit(1)

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        logging.critical(f"Could not parse '{path}': {e}")
        exit(1)

    if not isinstance(data, dict) or not data:
        logging.critical(f"'{path}' did not contain a character mapping.")
        exit(1)

    logging.info(f"Character sheet: {path}")
    return data


def load_character(name: str) -> str:
    """Load a character sheet and return it as prompt-ready text."""
    return _format_character(load_character_data(name))


def _first_present(data: dict, *keys):
    """Return the first non-empty value among ``keys`` (sheets vary in casing)."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def character_level(data: dict) -> int | None:
    """Extract the character's level, tolerating the label variants sheets use."""
    raw = _first_present(data, "Current Level", "current_level", "Level", "level")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    match = re.search(r"\d+", str(raw))
    return int(match.group(0)) if match else None


def _split_names(value) -> list[str]:
    """Split a sheet field like 'Eldritch Blast, Minor Illusion' into names."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[,;]", str(value))
    return [str(i).strip() for i in items if str(i).strip()]


def known_spells(data: dict) -> list[str]:
    """Names the character already has prepared.

    Book of Shadows picks must exclude these, and the model will happily suggest
    them anyway if it is not told.
    """
    raw = _first_present(
        data,
        "Known/Prepared Base Spells",
        "Known Prepared Base Spells",
        "Prepared Spells",
        "Known Spells",
    )
    return _split_names(raw)


def max_spell_level(data: dict) -> int | None:
    """Highest spell level the character can cast, inferred from class and level.

    Warlocks have a single slot level, so this both describes every slot and caps
    which spells are worth recommending.
    """
    cls = str(_first_present(data, "Class", "class") or "").lower()
    level = character_level(data)
    if level is None:
        return None
    if "warlock" in cls:
        # 2024 Warlock slot level: 1 (L1-2), 2 (L3-4), 3 (L5-6), 4 (L7-8), 5 (L9+).
        return min(5, max(1, (level + 1) // 2))
    # Other classes have a genuine spread; full-caster progression is the best
    # available approximation and is only used to bound recommendations.
    return min(9, max(1, (level + 1) // 2))


# --- RETRIEVAL ---
def _dedupe_by_spell(documents):
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


def _dedupe_spells(parsed_spells):
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


def _retrieve(db, query: str, where=None, k: int = RETRIEVAL_K):
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



def _exhaustive_lane(db, where):
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
        return _dedupe_spells(
            spells.spell_from_metadata(d.metadata) for d in _retrieve(db, "", where, RETRIEVAL_K)
        )
    return _dedupe_spells(
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
    known = known_spells(character)
    bucket = {"cantrips": [], "rituals": [], "ranked": []}

    bucket["cantrips"] = _exhaustive_lane(db, spells.book_cantrip_filter(exclude_names=known))
    bucket["rituals"] = _exhaustive_lane(db, spells.book_ritual_filter(exclude_names=known))

    if query:
        bucket["ranked"] = _rank_book_candidates(
            db, query, exclude_names=known, cantrips=len(bucket["cantrips"]), rituals=len(bucket["rituals"])
        )

    logging.info(
        f"Legal pool: {len(bucket['cantrips'])} cantrip(s), "
        f"{len(bucket['rituals'])} level 1 ritual(s), "
        f"{len(bucket['ranked'])} scenario-ranked."
    )
    return bucket


def _rank_book_candidates(db, query: str, *, exclude_names, cantrips: int, rituals: int):
    """Order book candidates by scenario relevance, for full-text selection only.

    Each lane is searched separately and the results sampled from both, so the model
    always sees ritual text as well as cantrip text - rituals are the less familiar
    half of the pick.
    """
    per_lane = max(1, FULL_TEXT_SPELLS // 2)
    ranked = []
    seen = set()

    for where in (
        spells.book_cantrip_filter(exclude_names=exclude_names),
        spells.book_ritual_filter(exclude_names=exclude_names),
    ):
        hits = _dedupe_by_spell(_retrieve(db, query, where, k=per_lane))
        for doc in hits[:per_lane]:
            key = doc.metadata.get("spell_name") or doc.metadata.get("filename")
            if key and key not in seen:
                seen.add(key)
                ranked.append(doc)
    return ranked


def _format_pool(bucket: dict, slot_level: int | None, limit: int | None = None) -> str:
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
    return "\n\n".join(sections)


def _format_full_text(bucket: dict, limit: int = FULL_TEXT_SPELLS) -> str:
    """Render full page text for the scenario-ranked candidates."""
    blocks = []
    for doc in list(bucket.get("ranked", []))[:limit]:
        meta = doc.metadata
        header = f"[{meta.get('spell_name') or meta.get('filename')} | level {meta.get('level')}]"
        blocks.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)


def _parse_args(argv=None):
    """Parse CLI flags for choosing the character sheet."""
    parser = argparse.ArgumentParser(
        prog="what-spellbook",
        description="Tome Warlock spellbook generator.",
    )
    parser.add_argument(
        "--character",
        metavar="NAME",
        help=(
            f"Character sheet stem in {CHARACTERS_DIR} "
            f"(default: ${'CHARACTER'} or '{DEFAULT_CHARACTER}')."
        ),
    )
    return parser.parse_args(argv)


# --- REPL INTERFACE ---
class SpellbookShell(cmd.Cmd):
    # Bare command names; the '/' prefix is added by the REPL and TAB completion.
    COMMANDS = ("scenario", "ask", "exit")

    intro = (
        "\n🔮 Tome Warlock Spellbook Generator Initialised.\n"
        "Commands:\n"
        "  /scenario <text> - Set a new tactical scenario and generate 3 books.\n"
        "  /ask <text>      - Ask a follow-up or refining question about the current books.\n"
        "  /exit            - Close the session.\n"
        "Type '/' and press TAB to complete a command.\n"
    )
    prompt = "TomeWarlock> "

    def __init__(self, vector_db, character_context, character=None):
        super().__init__()
        self.db = vector_db
        self.character_context = character_context
        # Structured sheet, when supplied by main(); falls back to rendering the
        # pre-formatted context so existing callers keep working.
        self.character = character if character is not None else {}
        self.llm = build_llm()
        self.last_response = ""
        self.current_scenario = ""
        self.pool_text = ""
        self.rule_context = prompts.load_rule_context(self.character, CONTEXT_DIR) if self.character else ""
        # readline must treat '/' as word text, not a separator, or TAB on '/s'
        # would report text 's' at begidx 1 and skip completenames entirely.
        if readline is not None:
            delims = readline.get_completer_delims()
            if "/" in delims:
                readline.set_completer_delims(delims.replace("/", ""))

    def completenames(self, text, *ignored):
        """Offer '/<command>' for a leading-slash token, the bare command otherwise.

        cmd's cmdloop rebinds readline's completer to self.complete after __init__,
        so this hook is the reliable place to inject slash completion.
        """
        if text.startswith("/"):
            return [f"/{name} " for name in self.COMMANDS if f"/{name}".startswith(text)]
        return super().completenames(text, *ignored)

    def parseline(self, line):
        """Accept the '/command' form by dropping one leading slash.

        cmd only recognises identchars as the command token, so '/scenario ruin'
        would otherwise parse as an empty command and land in default().
        """
        stripped = line.lstrip()
        if stripped.startswith("/"):
            line = stripped[1:]
        return super().parseline(line)

    @staticmethod
    def _extract_text(response):
        """Normalise Ollama's string output and ChatOpenAI's AIMessage to plain text."""
        if isinstance(response, str):
            return response
        text = getattr(response, "text", None)
        if callable(text):
            text = text()
        return text if text else str(getattr(response, "content", response))

    def _run_llm(self, prompt):
        """Call the selected backend and surface a clear error instead of a raw traceback.

        An empty completion is treated as a failure. Ollama's thinking models (for
        example qwen3.5) can spend the whole token budget on hidden reasoning and
        return an empty ``response``; silently printing nothing makes that look like a
        successful run.
        """
        try:
            text = self._extract_text(self.llm.invoke(prompt))
        except Exception as e:
            logging.error(f"LLM request failed: {e}")
            print(f"Request to the model failed: {e}")
            return None

        if not text.strip():
            logging.error(
                "The model returned an empty response. This usually means it used its "
                "entire token budget on internal reasoning, or the prompt exceeded the "
                "model's context window."
            )
            print(
                "The model returned an empty response. Try again, shorten the scenario, "
                "or use a larger model (OPENROUTER_API_KEY selects the OpenRouter backend)."
            )
            return None
        return text

    def do_scenario(self, arg):
        """Submit a brand new tactical scenario: /scenario <description>"""
        if not arg.strip():
            logging.error("Please provide a scenario description.")
            return

        self.current_scenario = arg
        slot_level = max_spell_level(self.character) if self.character else None

        # Stage 1: build the legal candidate pool. The character's class, pact and
        # subclass decide what can go in the book; the scenario only ranks which legal
        # candidates get their full text put in front of the model.
        logging.info(f"Building legal spell pool for: '{self.current_scenario}'...")
        bucket = gather_spell_candidates(
            self.db, character=self.character, query=self.current_scenario
        )

        if not bucket["cantrips"] and not bucket["rituals"]:
            print("There are no spells matching this character's eligibility rules.")
            return

        self.pool_text = _format_pool(bucket, slot_level)
        spell_data_context = _format_full_text(bucket)

        if not self.rule_context:
            logging.warning(
                f"No rule context found under {CONTEXT_DIR}/; the model gets no rules grounding."
            )

        # Stage 2: the model ranks an already-legal pool, with the rules and sheet in hand.
        full_prompt = prompts.full_prompt(
            character_text=self.character_context,
            rule_context=self.rule_context,
            scenario=self.current_scenario,
            pool_text=self.pool_text,
            spell_text=spell_data_context,
        )

        budget_warning = prompts.prompt_budget_warning(full_prompt)
        if budget_warning:
            logging.warning(budget_warning)

        self.last_response = self._run_llm(full_prompt)
        if self.last_response is None:
            self.last_response = ""
            return

        logging.info("="*50)
        print(self.last_response)
        self._warn_about_illegal_picks(bucket)
        logging.info("="*50)

    def _warn_about_illegal_picks(self, bucket):
        """Report any book pick that is not actually eligible.

        The pool is filtered before the model sees it, but a model can still pull a
        name from the rules context (or invent one). Without this check a book that
        cannot legally be written would be presented as ready to use.
        """
        problems = spells.validate_book_picks(
            self.last_response,
            bucket.get("cantrips", []),
            bucket.get("rituals", []),
            known=known_spells(self.character),
        )
        if not problems:
            return
        logging.warning("Illegal book picks in the model's answer: " + "; ".join(problems))
        print("\n⚠️  Some picks are not legal for the Book of Shadows:")
        for problem in problems:
            print(f"   - {problem}")
        print("   Verify each pick against the eligible list above before using it.")

    def do_ask(self, arg):
        """Ask a refining question about the last generated output: /ask <your question>"""
        if not self.last_response:
            logging.error("No books have been generated yet. Please set a scenario first using '/scenario <text>'.")
            return
        if not arg.strip():
            logging.error("Please provide a question.")
            return

        logging.info(f"Refining current choices based on: '{arg}'...")

        refine = prompts.refine_prompt(
            question=arg,
            previous_response=self.last_response,
            scenario=self.current_scenario,
            rule_context=self.rule_context,
            pool_text=self.pool_text,
        )

        self.last_response = self._run_llm(refine)
        if self.last_response is None:
            self.last_response = ""
            return
        logging.info("="*50)
        print(self.last_response)
        logging.info("="*50)

    def do_exit(self, arg):
        """Exit the script cleanly."""
        return True

    def do_EOF(self, arg):
        """Exit on Ctrl+D, same as /exit."""
        print()
        return True

    def default(self, line):
        logging.error(f"Unknown command: '{line}'. Use '/scenario <text>', '/ask <text>', or '/exit'.")

def _exit_on_sigterm(signum, frame):
    """Translate SIGTERM into Ctrl+C so both stop the shell the same way."""
    raise KeyboardInterrupt


def main(argv=None):
    """Start the watcher and REPL, shutting both down cleanly on Ctrl+C."""
    global watch_thread

    args = _parse_args(argv)
    # Precedence: --character flag, then the CHARACTER env var, then the default sheet.
    character_name = args.character or os.getenv("CHARACTER", DEFAULT_CHARACTER)
    character_data = load_character_data(character_name)
    my_character = _format_character(character_data)

    # SIGTERM has no default KeyboardInterrupt, so map it explicitly (e.g. for a container stop).
    signal.signal(signal.SIGTERM, _exit_on_sigterm)

    observer = get_observer()
    observer.start()
    watch_thread = threading.Thread(target=start_watching, args=(DOCS_DIR, observer), daemon=True)
    watch_thread.start()

    try:
        shell = SpellbookShell(ensure_db(), my_character, character_data)
        shell.cmdloop()
    except KeyboardInterrupt:
        # Ctrl+C escapes cmdloop's internal input() loop, so unwind here instead.
        print()
        logging.info("Interrupted by user.")
    finally:
        _stop_observer(observer)
        logging.info("Goodbye, Warlock.")


if __name__ == "__main__":
    main()
