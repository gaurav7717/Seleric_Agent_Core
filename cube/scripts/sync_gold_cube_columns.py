#!/usr/bin/env python3
"""
Sync ClickHouse gold.* column metadata into Cube YAML cubes and generate full-exposure views.

Adds any missing table columns as dimensions (strings/dates/bools) or measures (numeric sums).
Generates model/views/gold_full_views.yml — one view per gold table with every member exposed.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CUBES_DIR = ROOT / "model" / "cubes"
FULL_VIEWS_FILE = ROOT / "model" / "views" / "gold_full_views.yml"
ENV_FILE = ROOT / ".env"

SKIP_AUTO_MEASURE = frozenset({
    "brand_id", "report_date", "order_date", "order_id", "line_item_id",
    "customer_id", "transaction_id", "variant_id", "session_id",
    "hour_of_day", "campaign_id", "adset_id", "ad_id", "account_id",
    "pnl_key", "order_key", "campaign_key", "adset_key", "ad_key",
})

TIME_COLS = frozenset({
    "report_date", "order_date", "order_created_at", "order_updated_at",
    "created_at", "updated_at", "cancelled_at", "closed_at", "returned_at",
    "transaction_date", "session_date", "changed_at", "effective_from",
    "effective_to", "first_order_at", "last_order_at", "_loaded_at",
})

BOOL_PREFIXES = ("is_", "has_", "included_", "over_")


def load_ch_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def ch_describe(table: str, env: dict[str, str]) -> list[tuple[str, str]]:
    import subprocess

    q = f"DESCRIBE TABLE gold.{table} FORMAT JSONEachRow"
    url = (
        f"http://{env['CUBEJS_DB_USER']}:{env['CUBEJS_DB_PASS']}"
        f"@{env['CUBEJS_DB_HOST']}:{env['CUBEJS_DB_PORT']}/"
    )
    raw = subprocess.check_output(
        ["curl", "-sf", "-G", url, "--data-urlencode", f"query={q}"],
        text=True,
    )
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    return [(r["name"], r["type"]) for r in rows]


def cube_table_name(cube_file: Path) -> str | None:
    name = cube_file.stem  # gold_fct_orders
    if not name.startswith("gold_"):
        return None
    doc = yaml.safe_load(cube_file.read_text()) or {}
    cube = (doc.get("cubes") or [{}])[0]
    sql_table = cube.get("sql_table") or ""
    if sql_table.startswith("gold."):
        return sql_table.split(".", 1)[1]
    return name[len("gold_") :]


def is_numeric(ch_type: str) -> bool:
    t = ch_type.lower()
    return any(x in t for x in ("int", "float", "double", "decimal", "uint"))


def is_bool_col(name: str, ch_type: str) -> bool:
    t = ch_type.lower()
    if "bool" in t:
        return True
    if t.startswith("uint8") and name.startswith(BOOL_PREFIXES):
        return True
    return False


def measure_type(name: str, ch_type: str) -> tuple[str, str | None]:
    if name.endswith("_pct") or name.endswith("_rate") or "decimal(10" in ch_type.lower():
        return "number", "percent" if name.endswith("_pct") or name.endswith("_rate") else None
    return "sum", "currency" if "decimal" in ch_type.lower() else "number"


def dimension_type(name: str, ch_type: str) -> str:
    if name in TIME_COLS or "date" in ch_type.lower() or "datetime" in ch_type.lower():
        return "time"
    if is_bool_col(name, ch_type):
        return "boolean"
    return "string"


def existing_members(cube: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for section in ("measures", "dimensions"):
        for m in cube.get(section) or []:
            if m.get("name"):
                names.add(m["name"])
    return names


def build_measure(name: str, ch_type: str) -> dict[str, Any]:
    mtype, fmt = measure_type(name, ch_type)
    if mtype == "sum":
        entry: dict[str, Any] = {"name": name, "sql": name, "type": "sum"}
    else:
        entry = {"name": name, "sql": f"avg({name})", "type": "number"}
    if fmt:
        entry["format"] = fmt
    return entry


def build_dimension(name: str, ch_type: str) -> dict[str, Any]:
    dtype = dimension_type(name, ch_type)
    entry: dict[str, Any] = {"name": name, "sql": name, "type": dtype}
    if dtype == "time" and name == "report_date":
        entry["primary_key"] = True
    return entry


def sync_cube_file(path: Path, columns: list[tuple[str, str]]) -> int:
    doc = yaml.safe_load(path.read_text()) or {}
    cubes = doc.get("cubes") or []
    if not cubes:
        return 0
    cube = cubes[0]
    existing = existing_members(cube)
    measures = list(cube.get("measures") or [])
    dimensions = list(cube.get("dimensions") or [])
    added = 0

    for col, ctype in columns:
        if col in existing:
            continue
        if is_numeric(ctype):
            if col in SKIP_AUTO_MEASURE:
                dimensions.append(build_dimension(col, ctype))
            else:
                measures.append(build_measure(col, ctype))
        else:
            dimensions.append(build_dimension(col, ctype))
        existing.add(col)
        added += 1

    if added:
        cube["measures"] = measures
        cube["dimensions"] = dimensions
        header_lines: list[str] = []
        for line in path.read_text().splitlines(True):
            if line.startswith("cubes:"):
                break
            header_lines.append(line)
        if header_lines and not header_lines[-1].endswith("\n"):
            header_lines[-1] += "\n"
        path.write_text(
            "".join(header_lines)
            + yaml.dump({"cubes": cubes}, sort_keys=False, allow_unicode=True, default_flow_style=False)
        )

    return added


def view_suffix(path: Path, cube: dict[str, Any]) -> str | None:
    table = cube_table_name(path)
    if table:
        return table
    if cube.get("sql") and path.stem.startswith("gold_"):
        return path.stem[len("gold_") :]
    return None


def generate_full_views(cube_files: list[Path]) -> None:
    views: list[dict[str, Any]] = []
    for path in sorted(cube_files):
        doc = yaml.safe_load(path.read_text()) or {}
        cube = (doc.get("cubes") or [{}])[0]
        suffix = view_suffix(path, cube)
        if not suffix:
            continue
        cname = cube.get("name")
        if not cname:
            continue
        view_name = f"gold__{suffix}"
        includes: list[Any] = []
        for m in cube.get("measures") or []:
            if m.get("name"):
                includes.append(m["name"])
        for d in cube.get("dimensions") or []:
            if d.get("name"):
                includes.append(d["name"])
        views.append({
            "name": view_name,
            "title": f"Gold {suffix} (all columns)",
            "description": (
                f"Full exposure of gold.{suffix} — every synced column as a queryable member. "
                f"MCP: cube_query with view prefix {view_name}."
            ),
            "cubes": [{"join_path": cname, "includes": includes}],
        })

    FULL_VIEWS_FILE.write_text(
        "# Auto-generated by sync_gold_cube_columns.py — do not edit manually.\n"
        + yaml.dump({"views": views}, sort_keys=False, allow_unicode=True, default_flow_style=False)
    )


def main() -> None:
    env = load_ch_env()
    total_added = 0
    cube_files = sorted(CUBES_DIR.glob("gold_*.yml"))

    for path in cube_files:
        table = cube_table_name(path)
        if not table:
            print(f"skip (no sql_table): {path.name}")
            continue
        try:
            cols = ch_describe(table, env)
        except Exception as e:
            print(f"skip {table}: {e}")
            continue
        n = sync_cube_file(path, cols)
        total_added += n
        print(f"{path.name}: +{n} members ({len(cols)} CH columns)")

    generate_full_views(cube_files)
    print(f"\nTotal members added: {total_added}")
    n_views = len((yaml.safe_load(FULL_VIEWS_FILE.read_text()) or {}).get("views") or [])
    print(f"Wrote {FULL_VIEWS_FILE} ({n_views} views)")


if __name__ == "__main__":
    main()
