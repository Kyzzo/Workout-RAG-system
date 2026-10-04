"""
Re-verify the citations behind the app's mechanical rules (e.g. the even
split of weekly sets across sessions) against the current research corpus.
Run after ingesting new papers so the rules can cite them.

Usage (from backend/):
    uv run python -m scripts.refresh_rule_justifications
"""

from app.database import SessionLocal
from app.rag.rule_justifications import RULES, justify_rule


def main():
    db = SessionLocal()
    try:
        for key in RULES:
            record = justify_rule(db, key, refresh=True)
            sources = sorted({c.citation.title for c in record.supporting_citations})
            print(f"{key}: {len(record.supporting_citations)} supporting excerpt(s) from {sources or 'none'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
