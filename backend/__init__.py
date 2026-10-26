"""The backend: a domain library, a CLI and an HTTP API.

Layout::

    backend/libs/    rules, retrieval, prompting, caching  (the domain - no I/O surfaces)
    backend/cli/     the terminal front end
    backend/api/     the HTTP front end
    backend/app.py   the console entry point

Import everything by its full path from the repo root::

    from backend.libs import service, characters, config
    from backend.cli import shell
    from backend.api.main import create_app

There is deliberately **no sys.path manipulation here**. Every module is imported as
``backend.<layer>.<module>``, which works because the repo root is the import root - the
same directory that holds ``pyproject.toml`` and ``.env``. Earlier the code lived in
``src/`` and used flat names (``from backend import config``), which needed a bootstrap
that inserted ``src/`` onto ``sys.path`` and made a directory's *name* do work its
contents did not. Removing that is the reason ``src/`` is gone.

Run from the repo root, or install with ``pip install -e .``.
"""

from __future__ import annotations
