"""
Re-verify the citations behind the app's mechanical rules (e.g. the even
split of weekly sets across sessions) against the current research corpus.
Run after ingesting new papers so the rules can cite them.

Usage (from backend/):
    uv run python -m scripts.refresh_rule_justifications [rule_key ...]

Each rule costs a judge call per candidate excerpt, so pass the keys of the
rules a change can affect; with none, every rule is refreshed.
"""

import sys

from app.database import SessionLocal
from app.rag.rule_justifications import RULES, justify_rule


def main():
    db = SessionLocal()
    try:
        keys = sys.argv[1:] or list(RULES)
        unknown = [k for k in keys if k not in RULES]
        if unknown:
            sys.exit(f"Unknown rule(s): {', '.join(unknown)}")
        for key in keys:
            record = justify_rule(db, key, refresh=True)
            sources = sorted({c.citation.title for c in record.supporting_citations})
            print(f"{key}: {len(record.supporting_citations)} supporting excerpt(s) from {sources or 'none'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
