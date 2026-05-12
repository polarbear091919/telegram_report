"""Entry point: `python -m langgraph_tagger.analytics`.

Spawns `streamlit run` on app.py with headless mode + usage stats disabled
to bypass Streamlit's first-run prompt. Operator opens
http://localhost:8501 manually.
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
