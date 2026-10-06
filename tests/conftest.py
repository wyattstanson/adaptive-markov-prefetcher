"""Put the `python/` source directory on the import path for the test run."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "python"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
