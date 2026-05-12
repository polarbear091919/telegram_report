"""Entry point: `python -m langgraph_tagger.review_viewer`.

Spawns `streamlit run` on app.py so the operator does not need to remember
the streamlit CLI syntax. Headless mode + usage stats disabled bypass
Streamlit's first-run prompt; operator opens http://localhost:8501 manually.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app_path = Path(__file__).with_name('app.py')
    cmd = [
        sys.executable, '-m', 'streamlit', 'run', str(app_path),
        '--server.headless=true',
        '--browser.gatherUsageStats=false',
    ]
    return subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main())
