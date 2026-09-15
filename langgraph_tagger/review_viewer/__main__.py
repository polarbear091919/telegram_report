"""Compatibility entry point for Research Desk's migrated review queue."""
from __future__ import annotations

import sys
from langgraph_tagger.workspace.__main__ import main as run_workspace


def main() -> int:
    return run_workspace(view='review')


if __name__ == '__main__':
    sys.exit(main())
