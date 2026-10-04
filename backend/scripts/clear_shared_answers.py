"""
Delete every stored shared answer (app/shared_answers.py) so each question
is generated and judged again against the current corpus. Run after
ingesting papers - locally and against production (DATABASE_URL override),
the same as refresh_rule_justifications. Programs already generated keep
their values; only new generations are affected.

Prompt or model changes don't need this: bump ANSWER_VERSION instead.
Shared answers apply to every program, so it's worth reviewing them with
--list; --key clears just one (e.g. a value you want regenerated).

Usage (from backend/):
    uv run python -m scripts.clear_shared_answers --list
    uv run python -m scripts.clear_shared_answers --key "<key from --list>"
    uv run python -m scripts.clear_shared_answers          # clear all
"""

import argparse

from app import models
from app.database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="List or clear stored shared answers")
    parser.add_argument("--list", action="store_true", help="show stored answers without clearing")
    parser.add_argument("--key", help="clear only this answer")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(models.SharedAnswer).order_by(models.SharedAnswer.key)
        if args.list:
            for answer in query:
                papers = sorted({c.citation.title for c in answer.citations
                                 if c.verification_status in models.SUPPORTED_VERIFICATION_STATUSES})
                print(f"{answer.value:>18}  {answer.key}  ({', '.join(papers)})")
            return
        if args.key:
            query = query.filter(models.SharedAnswer.key == args.key)
        answers = query.all()
        for answer in answers:
            db.delete(answer)  # ORM delete so its citation rows cascade
        db.commit()
        print(f"cleared {len(answers)} shared answer(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
