"""GridGuard demo launcher — starts the operator dashboard.

Usage:
    python3 run_ui.py            # serve on http://localhost:8000
    python3 run_ui.py 8080       # custom port
    APP_PORT=8080 python3 run_ui.py

Requires only the Python standard library (no pip install needed).
AI briefings work offline via the built-in mock provider; set LLM_BASE_URL /
LLM_API_KEY (see src/.env.example) to use a live model instead.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from api.server import run  # noqa: E402
from api.grid_service import default_db_path  # noqa: E402


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("APP_PORT", "8000"))
    run(port, default_db_path())
