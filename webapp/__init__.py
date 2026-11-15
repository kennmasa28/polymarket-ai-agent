"""PolyAgent web app (Flask): agent chat & trading, manual orders, log analysis.

Run with ``python -m webapp`` (see README for login setup).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
# The agent modules in src/ use flat imports (``import config``, ``from trade import TRADE``).
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from .app import create_app  # noqa: E402

__all__ = ["create_app", "PROJECT_ROOT"]
