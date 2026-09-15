"""Compatibility entry point for the migrated Research Desk analytics UI."""
from __future__ import annotations

import sys
from langgraph_tagger.workspace.__main__ import main as run_workspace


def main() -> int:
    return run_workspace(view='market')


if __name__ == '__main__':
    sys.exit(main())
