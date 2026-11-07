"""Vector index lifecycle: build, validate, rebuild.

The index carries spell metadata (level, school, class list, ritual) so eligibility
can be filtered inside Chroma rather than in the prompt. Importing this module must
never scan, embed, or delete anything - ``ensure_db()`` is called explicitly.

One collection holds three kinds of text, told apart by ``doc_type``: the spell corpus
(``spell``), the magic items that share its directory (``item``), and the vendored 2024 SRD
(``srd``). They share a collection because they are searched together - a reader asking
"what does cover do" wants the rule and the spells that grant it - but they are *not*
interchangeable, so every eligibility filter names the type it wants. See
``spells.DOC_TYPE_SPELL``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from . import config, rules, spells, srd

# The embeddings client is built lazily so importing this module never talks to Ollama.
_embeddings = None

# SRD sections are chunked with the same budget as a spell page, because the two are read
# by the same search and a rule that arrived in 3000-character pieces would crowd out the
# spells beside it.
SRD_CHUNK_SIZE = 1200
SRD_CHUNK_OVERLAP = 150


def get_embeddings():
    """Return the process-wide embeddings client, creating it on first use."""
    global _embeddings
    if _embeddings is None:
        from langchain_ollama import OllamaEmbeddings

        _embeddings = OllamaEmbeddings(model=config.EMBEDDING_MODEL)
    return _embeddings


def index_metadata(db_dir=None):
    """Return the stored index metadata mapping, or {} when unreadable.

    Opening a Chroma store creates the directory as a side effect, so callers must
    check for the sqlite file first.
    """
    db_dir = db_dir or config.DB_DIR
    try:
        db = Chroma(persist_directory=str(config.resolve(db_dir)), embedding_function=get_embeddings())
        collection = db._collection
        return dict(collection.metadata or {})
    except Exception:
        logging.debug(f"Could not read index metadata at {db_dir}.", exc_info=True)
        return {}


def db_is_valid(db_dir: str) -> bool:
    """Load the persisted Chroma index and confirm it holds data of the current shape.

    Returns False unless the collection opens cleanly, contains embeddings, and was
    written at the current ``INDEX_VERSION``. The version check matters because the
    metadata fields used for filtering were added later; an older index would make
    every metadata filter silently return nothing.
    """
    # Opening a Chroma store creates the directory and sqlite file as a side effect,
    # so bail out early when there is no index on disk yet.
    if not (config.resolve(db_dir) / "chroma.sqlite3").exists():
        return False

    try:
        db = Chroma(persist_directory=str(config.resolve(db_dir)), embedding_function=get_embeddings())
        payload = db.get(include=["embeddings"])
        # `embeddings` comes back as a numpy array, whose truth value is ambiguous -
        # `not`/`bool()` on it raises, so length is the only safe emptiness test.
        if payload is None or len(payload["embeddings"]) == 0:
            return False
    except Exception as e:
        logging.warning(f"Could not read index at {db_dir} ({e}); treating as unusable.")
        return False

    version = index_metadata(db_dir).get("index_version")
    if version != config.INDEX_VERSION:
        logging.info(
            f"Index metadata version {version!r} does not match "
            f"{config.INDEX_VERSION}; rebuilding."
        )
        return False
    return True


def reset_db(db_dir: str) -> None:
    """Delete the persisted index so it can be rebuilt from scratch.

    Chroma caches its sqlite connection per persist path. If we delete the directory
    while that cached client is still alive, the rebuild reuses the stale handle and
    fails with "attempt to write a readonly database". Dropping the cache first forces
    a fresh client against the new directory.
    """
    SharedSystemClient.clear_system_cache()
    path = config.resolve(db_dir)
    if path.exists():
        shutil.rmtree(path)


def build_index(docs_path: Path, db_dir: str, srd_path: Path | None = None):
    """Read every spell markdown file, chunk it, and persist a fresh Chroma index.

    The vendored SRD is indexed into the same collection, one row per section. It is
    chunked by *heading* rather than by the spell splitter, because a rule's identity is
    its heading: ``### Cover`` is the rule, and a chunk that began mid-table would be a
    fragment with no name. Sections longer than the chunk budget are split further, so a
    1,750-line class chapter does not become one embedding that matches everything weakly.
    """
    md_files = list(docs_path.rglob("*.md"))
    logging.info(f"Discovered {len(md_files)} spell markdown files across subdirectories.")

    logging.info(
        f"Processing and vectorizing all {len(md_files)} files. This will take a moment..."
    )
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
        raise IndexUnavailable(f"No readable spell documents under {docs_path}.")

    # Split using Markdown header tags matching the exact spell sheet structure
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

    final_docs.extend(_srd_documents(srd_path))

    # ``Chroma.from_documents`` *adds* to an existing collection rather than replacing it,
    # so building over a live index would double every row. ``ensure_db`` resets first, but
    # a direct call does not - and a doubled index is invisible until a count looks wrong.
    reset_db(db_dir)

    db = Chroma.from_documents(
        final_docs,
        get_embeddings(),
        persist_directory=str(config.resolve(db_dir)),
        collection_metadata={"index_version": config.INDEX_VERSION, "hnsw:space": "l2"},
    )
    logging.info(f"Rebuild Complete: Indexed {len(final_docs)} total text chunks into ChromaDB.")
    return db


def _srd_documents(srd_path: Path | None = None) -> list[Document]:
    """The vendored SRD as indexable chunks, one row per section.

    A missing SRD directory is not an error: the spell corpus is the index's reason to
    exist, and a checkout without the vendored rules should still build a usable index
    rather than refuse. It is logged, because a silently rule-less index is the kind of
    thing that is only noticed when an answer is wrong.
    """
    directory = config.resolve(srd_path or rules.SRD_DIR)
    if not directory.is_dir():
        logging.warning(
            f"No vendored SRD at {directory}; indexing the spell corpus only. "
            "Rules text will not be searchable."
        )
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=SRD_CHUNK_SIZE, chunk_overlap=SRD_CHUNK_OVERLAP
    )
    documents: list[Document] = []
    for document, heading, body in srd.sections():
        metadata = spells.build_srd_metadata(
            document=document.name, title=document.title, heading=heading.text,
            slug=heading.slug, path=document.path, level=heading.level,
        )
        # The heading is repeated in the body so a chunk that was split away from its
        # heading still says what it is about - the same reason a spell's name is written
        # into its own text.
        text = f"{document.title} > {heading.text}\n\n{body}"
        for chunk in splitter.create_documents([text], metadatas=[metadata]):
            documents.append(chunk)

    logging.info(
        f"Indexed {len(documents)} SRD chunk(s) from {len(srd.documents())} vendored file(s)."
    )
    return documents


class IndexUnavailable(RuntimeError):
    """Raised when the index cannot be built or loaded.

    A library must not call ``sys.exit``: the caller (CLI, API, test) decides how to
    report a missing corpus.
    """


def ensure_db(docs_path=None, db_dir=None):
    """Return the vector index, rebuilding from source only when it is unusable.

    If the spell source directory is missing the persisted index is loaded as-is.
    A rebuild happens only when there are enough source files AND the index is absent
    or unreadable, so a merely-existing directory is never wiped.

    This runs from the caller rather than at import time: importing this module must
    never scan, embed, or delete anything.
    """
    docs_path = config.resolve(docs_path or config.DOCS_DIR)
    db_dir = db_dir or config.DB_DIR

    if not docs_path.exists():
        raise IndexUnavailable(
            f"The directory '{docs_path}' does not exist. Check your path layout."
        )

    md_files = list(docs_path.rglob("*.md"))
    if len(md_files) > 10 and not db_is_valid(db_dir):
        logging.warning("Database reset triggered. Wiping corrupt/missing/unreadable index...")
        # ``build_index`` resets the directory itself, so the wipe is not repeated here.
        return build_index(docs_path, db_dir)

    logging.debug("Loading existing vector index from DB_DIR...")
    return Chroma(persist_directory=str(config.resolve(db_dir)), embedding_function=get_embeddings())
