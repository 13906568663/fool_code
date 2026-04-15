"""Quick launch script — run with: uv run run.py"""

import io
import os
import sys

if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from fool_code.main import main

if __name__ == "__main__":
    main()
