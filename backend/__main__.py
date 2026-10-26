"""``python -m backend`` runs the CLI.

Run from the repo root, or from anywhere once the project is installed, because the
imports are ``backend.*``. There is deliberately no equivalent ``backend/app.py``: running
a file directly puts *its own* directory on ``sys.path``, not the repo root, so
``python backend/app.py`` could never work - and a launch command that crashes is worse
than one that does not exist.
"""

from __future__ import annotations

from backend.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
