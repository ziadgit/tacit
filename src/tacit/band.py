"""Access to the Vexo Open kit's library, used straight from the ./vexo-open-kit clone.

The kit is not pip-installed on purpose (its AGENTS.md): we put its folders on sys.path.
"""

import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "vexo-open-kit"
KIT_PYTHON = KIT / "python"
KIT_EXAMPLES = KIT / "examples" / "python"  # speech.py (Deepgram), ai.py (OpenAI)


def use_kit() -> None:
    """Make `vexo_open`, `speech` and `ai` importable. Call before importing them."""
    if not KIT_PYTHON.is_dir():
        raise RuntimeError("vexo-open-kit/ is missing: run scripts/bootstrap.sh")
    for p in (KIT_PYTHON, KIT_EXAMPLES):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
