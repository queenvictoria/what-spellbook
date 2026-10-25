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

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Pull OPENROUTER_API_KEY (and friends) out of the untracked .env file next to this script.
ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE)

# --- CONFIGURATION ---
DOCS_DIR = "./data/reddit-spence_post/Spells"
DB_DIR = "./data/chroma_db"

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
def _db_is_valid(db_dir: str) -> bool:
    """Load the persisted Chroma index and confirm it actually contains data.

    Returns True only if the collection opens cleanly AND holds embeddings.
    This replaces the previous broken guard that wiped any existing directory.
    """
    # Opening a Chroma store creates the directory and sqlite file as a side effect,
    # so bail out early when there is no index on disk yet.
    if not (Path(db_dir) / "chroma.sqlite3").exists():
        return False

    try:
        db = Chroma(persist_directory=db_dir, embedding_function=get_embeddings())
        payload = db.get(include=["embeddings", "documents"])
        return payload is not None and len(payload["embeddings"]) > 0
    except Exception:
        logging.debug(f"Could not load/validate index at {db_dir}; treating as corrupt.")
        return False


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

            # Extract tags like #Level5, #Conjuration for metadata filtering
            tags = re.findall(r"#(\w+)", content)

            # Secure the spell name explicitly inside the document body text block
            spell_title = p.stem.replace("-", " ").title()
            secured_content = f"Spell Name: {spell_title}\n\n{content}"

            metadata = {
                "source": str(p),
                "filename": p.name,
                "tags": ", ".join(tags)
            }
            documents.append(Document(page_content=secured_content, metadata=metadata))
        except Exception as e:
            logging.error(f"Could not read file {p}: {e}")

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

    db = Chroma.from_documents(final_docs, get_embeddings(), persist_directory=db_dir)
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


def load_character(name: str) -> str:
    """Load data/characters/<name>.yaml and return it as prompt-ready text.

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
    return _format_character(data)


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

    def __init__(self, vector_db, character_context):
        super().__init__()
        self.db = vector_db
        self.character_context = character_context
        self.llm = build_llm()
        self.last_response = ""
        self.current_scenario = ""
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
        """Call the selected backend and surface a clear error instead of a raw traceback."""
        try:
            return self._extract_text(self.llm.invoke(prompt))
        except Exception as e:
            logging.error(f"LLM request failed: {e}")
            print(f"Request to the model failed: {e}")
            return None

    def do_scenario(self, arg):
        """Submit a brand new tactical scenario: /scenario <description>"""
        if not arg.strip():
            logging.error("Please provide a scenario description.")
            return

        self.current_scenario = arg
        logging.info(f"Searching your comprehensive grimoire for: '{self.current_scenario}'...")

        # Pulling a robust k=30 footprint now that the database collection is healthy
        retriever = self.db.as_retriever(search_kwargs={"k": 30})
        relevant_spells = retriever.invoke(self.current_scenario)

        logging.info(f"Retrieved {len(relevant_spells)} spells from the grimoire.")

        # If there are no spells then print a message and exit.
        if not relevant_spells:
            print(f"There are no relevant spells for that request.")
            return

        formatted_chunks = []
        for doc in relevant_spells:
            meta_header = f"[Spell File: {doc.metadata.get('filename')} | Tags: {doc.metadata.get('tags', 'None')}]"
            formatted_chunks.append(f"{meta_header}\n{doc.page_content}")

        spell_data_context = "\n\n---\n\n".join(formatted_chunks)

        system_prompt = (
            "You are an expert D&D 5.5e (2024) tactical optimizer. Your user is a Warlock utilizing "
            "the Pact of the Tome feature during a Short Rest to swap out their Book of Shadows spells. "
            "Analyze the provided character profile and tactical scenario. Select optimal spells from the retrieved data pool "
            "and organize them into exactly three themed, distinct book options matching the scenario."
        )

        full_prompt = f"""
        System: {system_prompt}

        === CHARACTER PROFILE ===
        {self.character_context}

        === TACTICAL SCENARIO ===
        {self.current_scenario}

        === RETRIEVED SPELL DATA POOL ===
        {spell_data_context}

        === OUTPUT REQUIREMENTS ===
        Provide EXACTLY 3 alternate spellbook loadouts (Book 1, Book 2, Book 3).
        For each book:
        1. Give it a distinct tactical theme name.
        2. List the selected spells/cantrips.
        3. Provide a brief 'How to use' strategic breakdown for that scenario.
        """

        self.last_response = self._run_llm(full_prompt)
        if self.last_response is None:
            self.last_response = ""
            return
        logging.info("="*50)
        print(self.last_response)
        logging.info("="*50)

    def do_ask(self, arg):
        """Ask a refining question about the last generated output: /ask <your question>"""
        if not self.last_response:
            logging.error("No books have been generated yet. Please set a scenario first using '/scenario <text>'.")
            return
        if not arg.strip():
            logging.error("Please provide a question.")
            return

        logging.info(f"Refining current choices based on: '{arg}'...")

        refine_prompt = f"""
        You are continuing the conversation as the D&D 5.5e tactical optimizer.

        Here is the original scenario: {self.current_scenario}
        Here are the 3 books you previously proposed:
        {self.last_response}

        The user has a refining request/question: {arg}

        Adjust your recommendations or answer the question based strictly on this context.
        """

        self.last_response = self._run_llm(refine_prompt)
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
    my_character = load_character(character_name)

    # SIGTERM has no default KeyboardInterrupt, so map it explicitly (e.g. for a container stop).
    signal.signal(signal.SIGTERM, _exit_on_sigterm)

    observer = get_observer()
    observer.start()
    watch_thread = threading.Thread(target=start_watching, args=(DOCS_DIR, observer), daemon=True)
    watch_thread.start()

    try:
        shell = SpellbookShell(ensure_db(), my_character)
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
