#!/usr/bin/env python3
"""Validate and permanently finalize all corpus-v1 partitions."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


SCRIPT_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = SCRIPT_DIR / "corpus-v1.json"
REQUIRED_TABLES = (
    "core_year",
    "core_month",
    "core_day",
    "core_day_schedule",
    "core_event_occurrence",
    "core_parasha_occurrence",
    "core_leyning_occurrence",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_blocks(contract: dict[str, Any]) -> list[tuple[int, int, str]]:
    first = int(contract["hebrewYearRange"]["first"])
    last = int(contract["hebrewYearRange"]["last"])
    size = int(contract["partitioning"]["yearsPerBlock"])
    blocks = []
    for start in range(first, last + 1, size):
        end = min(start + size - 1, last)
        blocks.append((start, end, f"block={start:04d}-{end:04d}"))
    return blocks


def parquet_paths(root: Path, table: str) -> list[str]:
    return [
        str(path)
        for path in sorted(root.glob(f"block=*/{table}.parquet"))
    ]


def scalar(connection: duckdb.DuckDBPyConnection, query: str, paths: list[str]) -> Any:
    return connection.execute(query, [paths]).fetchone()[0]


def validate_global_tables(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    expected_years: int,
) -> dict[str, Any]:
    paths = {table: parquet_paths(root, table) for table in REQUIRED_TABLES}
    year_rows, unique_years, first_year, last_year = connection.execute(
        """
        SELECT count(*), count(DISTINCT hebrew_year),
               min(hebrew_year), max(hebrew_year)
        FROM read_parquet(?, union_by_name = true)
        """,
        [paths["core_year"]],
    ).fetchone()
    if year_rows != expected_years or unique_years != year_rows:
        raise RuntimeError(
            f"year table mismatch: rows={year_rows}, unique={unique_years}, "
            f"expected={expected_years}"
        )

    day_rows, unique_days, first_day, last_day = connection.execute(
        """
        SELECT count(*), count(DISTINCT absolute_day),
               min(absolute_day), max(absolute_day)
        FROM read_parquet(?, union_by_name = true)
        """,
        [paths["core_day"]],
    ).fetchone()
    expected_day_rows = scalar(
        connection,
        """
        SELECT sum(days_in_year)
        FROM read_parquet(?, union_by_name = true)
        """,
        paths["core_year"],
    )
    if (
        day_rows != expected_day_rows
        or unique_days != day_rows
        or last_day - first_day + 1 != day_rows
    ):
        raise RuntimeError(
            f"global day spine mismatch: rows={day_rows}, unique={unique_days}, "
            f"expected={expected_day_rows}, bounds={first_day}:{last_day}"
        )

    results: dict[str, Any] = {
        "core_year": {
            "rows": year_rows,
            "first_year": first_year,
            "last_year": last_year,
        },
        "core_day": {
            "rows": day_rows,
            "first_absolute_day": first_day,
            "last_absolute_day": last_day,
            "native_powerbi_dates": scalar(
                connection,
                """
                SELECT count(powerbi_date)
                FROM read_parquet(?, union_by_name = true)
                """,
                paths["core_day"],
            ),
        },
    }

    day_keys = paths["core_day"]
    day_schedule_paths = paths["core_day_schedule"]
    day_schedule_rows, day_schedule_keys = connection.execute(
        """
        SELECT count(*), count(DISTINCT (absolute_day, schedule))
        FROM read_parquet(?, union_by_name = true)
        """,
        [day_schedule_paths],
    ).fetchone()
    if day_schedule_rows != day_rows * 2 or day_schedule_keys != day_schedule_rows:
        raise RuntimeError(
            "global core_day_schedule must contain one row per day and schedule"
        )
    missing_schedule_days = connection.execute(
        """
        SELECT count(*)
        FROM read_parquet(?, union_by_name = true) AS schedule_day
        ANTI JOIN read_parquet(?, union_by_name = true) AS day
          USING (absolute_day)
        """,
        [day_schedule_paths, day_keys],
    ).fetchone()[0]
    if missing_schedule_days:
        raise RuntimeError(
            f"core_day_schedule has {missing_schedule_days} rows outside the day spine"
        )
    results["core_day_schedule"] = {"rows": day_schedule_rows}

    for table in REQUIRED_TABLES:
        if table in ("core_year", "core_day", "core_day_schedule"):
            continue
        table_paths = paths[table]
        rows = scalar(
            connection,
            "SELECT count(*) FROM read_parquet(?, union_by_name = true)",
            table_paths,
        )
        table_result: dict[str, Any] = {"rows": rows}
        if table.endswith("_occurrence"):
            unique_ids = scalar(
                connection,
                """
                SELECT count(DISTINCT occurrence_id)
                FROM read_parquet(?, union_by_name = true)
                """,
                table_paths,
            )
            if unique_ids != rows:
                raise RuntimeError(
                    f"{table} contains {rows - unique_ids} duplicate occurrence IDs"
                )
            missing_days = connection.execute(
                """
                SELECT count(*)
                FROM read_parquet(?, union_by_name = true) AS occurrence
                ANTI JOIN read_parquet(?, union_by_name = true) AS day
                  USING (absolute_day)
                """,
                [table_paths, day_keys],
            ).fetchone()[0]
            if missing_days:
                raise RuntimeError(
                    f"{table} has {missing_days} rows outside the day spine"
                )
            table_result["unique_occurrence_ids"] = unique_ids
        results[table] = table_result
    return results


def finalize(root: Path) -> Path:
    root = root.resolve()
    contract = load_json(CONTRACT_PATH)
    final_manifest = root / "manifest.json"
    if final_manifest.exists():
        raise FileExistsError(
            f"{final_manifest} already exists; finalized corpora cannot be rewritten"
        )

    expected = expected_blocks(contract)
    actual_names = sorted(
        path.name for path in root.glob("block=*") if path.is_dir()
    )
    expected_names = [name for _, _, name in expected]
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        raise RuntimeError(f"partition set mismatch; missing={missing}, extra={extra}")

    source_packages: dict[str, str] | None = None
    source_hashes: dict[str, str] | None = None
    partition_entries = []
    for start, end, name in expected:
        partition = root / name
        manifest_path = partition / "manifest.json"
        manifest = load_json(manifest_path)
        if (
            manifest["corpus_version"] != contract["corpusVersion"]
            or manifest["start_year"] != start
            or manifest["end_year"] != end
        ):
            raise RuntimeError(f"{name} manifest does not match its required range")
        if source_packages is None:
            source_packages = manifest["source_packages"]
            source_hashes = manifest["source_hashes"]
        elif (
            manifest["source_packages"] != source_packages
            or manifest["source_hashes"] != source_hashes
        ):
            raise RuntimeError(f"{name} was built from different immutable sources")

        for file_name, expected_file in manifest["files"].items():
            path = partition / file_name
            if not path.exists():
                raise RuntimeError(f"{path} is missing")
            actual_hash = sha256(path)
            if actual_hash != expected_file["sha256"]:
                raise RuntimeError(f"{path} checksum does not match its manifest")
        partition_entries.append(
            {
                "block": manifest["block"],
                "manifest_sha256": sha256(manifest_path),
                "files": manifest["files"],
            }
        )

    with duckdb.connect() as connection:
        validation = validate_global_tables(
            connection,
            root,
            int(contract["hebrewYearRange"]["last"])
            - int(contract["hebrewYearRange"]["first"])
            + 1,
        )

    result = {
        "corpus_version": contract["corpusVersion"],
        "status": "complete-immutable",
        "contract_sha256": sha256(CONTRACT_PATH),
        "finalizer_sha256": sha256(Path(__file__).resolve()),
        "source_packages": source_packages,
        "source_hashes": source_hashes,
        "partition_count": len(partition_entries),
        "partitions": partition_entries,
        "validation": validation,
        "immutability": contract["immutability"],
        "attribution": "Hebcal.com; generated content licensed CC BY 4.0",
    }
    with final_manifest.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    provenance = {
        "finalized_utc": datetime.now(UTC).isoformat(),
        "content_manifest_sha256": sha256(final_manifest),
        "corpus_id": f"sha256:{sha256(final_manifest)}",
        "validation_tool": f"DuckDB {duckdb.__version__}",
    }
    provenance_path = root / "provenance.json"
    with provenance_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(provenance, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return final_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(finalize(args.corpus_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
