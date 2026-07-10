#!/usr/bin/env python3
"""Fail if any Cube YAML references the legacy serve.* database schema."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUBES_DIR = ROOT / "model" / "cubes"

# Match serve.mart_* or sql_table: serve.* but not comments-only lines starting with #
SERVE_DB = re.compile(
    r"(?m)^[^#\n]*\bserve\.(mart_|fct_|dim_|)",
)
SQL_TABLE_SERVE = re.compile(r"sql_table:\s*serve\.", re.I)
FROM_SERVE = re.compile(r"\bFROM\s+serve\.", re.I)


def main() -> int:
    errors: list[str] = []
    for path in sorted(CUBES_DIR.glob("*.yml")):
        text = path.read_text()
        if SQL_TABLE_SERVE.search(text):
            errors.append(f"{path.name}: sql_table references serve.*")
        if FROM_SERVE.search(text):
            errors.append(f"{path.name}: SQL FROM serve.*")
        for m in SERVE_DB.finditer(text):
            line = text[: m.start()].count("\n") + 1
            errors.append(f"{path.name}:{line}: serve.* DB reference in active YAML")

    if errors:
        print("validate_no_serve_db: FAILED\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"validate_no_serve_db: OK ({len(list(CUBES_DIR.glob('*.yml')))} cube files, no serve.* DB refs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
