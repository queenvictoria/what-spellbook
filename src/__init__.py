"""Application packages: ``backend`` (rules, retrieval, prompting, cache) and ``cli``.

This package bootstraps its own directory onto ``sys.path`` so the two subpackages can
import each other with flat names (``from backend import config``) regardless of how the
app is launched:

    python main.py            # the shim adds src/ itself
    python -m src.cli.app     # this __init__ runs first and adds src/
    pytest                    # tests add src/ in conftest

Without this, ``python -m src.cli.app`` would put only the repo root on the path and
``import backend`` would fail, while ``python main.py`` worked - a difference that is
easy to miss and confusing to debug.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
