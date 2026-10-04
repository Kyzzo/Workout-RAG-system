"""
One-off: rename wizard days saved before repeated day types were lettered
('Upper 1', 'Upper 2' -> 'Upper A', 'Upper B'). Only renames names that are
exactly a split day type plus a number, so hand-named days are left alone.

Usage (from backend/):
    uv run python -m scripts.letter_day_names          # dry run
    uv run python -m scripts.letter_day_names --apply
"""

import re
import sys

from app import models
from app.database import SessionLocal
from app.splits import SPLITS

_TYPES = sorted({t.name for split in SPLITS.values() for t in split.day_types}, key=len, reverse=True)
_PATTERN = re.compile(rf"^({'|'.join(re.escape(t) for t in _TYPES)}) ([1-9])$")


def main():
    apply = "--apply" in sys.argv
    db = SessionLocal()
    try:
        renamed = 0
        for day in db.query(models.DayTemplate).all():
            m = _PATTERN.match(day.name)
            if not m:
                continue
            new = f"{m.group(1)} {chr(ord('A') + int(m.group(2)) - 1)}"
            print(f"day {day.id}: {day.name!r} -> {new!r}")
            day.name = new
            renamed += 1
        if apply:
            db.commit()
        print(f"{renamed} day(s) {'renamed' if apply else 'would be renamed (dry run)'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
