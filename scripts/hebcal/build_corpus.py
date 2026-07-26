#!/usr/bin/env python3
"""Build one new immutable Hebcal corpus partition.

This command deliberately has no overwrite option. If a completed partition
needs correction, create a new corpus version instead of replacing core rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


SCRIPT_DIR = Path(__file__).resolve().parent
CONTRACT_PATH = SCRIPT_DIR / "corpus-v1.json"
GENERATOR_PATH = SCRIPT_DIR / "generate_corpus.mjs"
IMMUTABLE_SOURCE_PATHS = (
    CONTRACT_PATH,
    GENERATOR_PATH,
    Path(__file__).resolve(),
    SCRIPT_DIR / "package.json",
    SCRIPT_DIR / "package-lock.json",
    SCRIPT_DIR / "requirements.txt",
)

TABLES = {
    "core_year": {
        "order": "hebrew_year",
        "select": """
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(first_absolute_day AS INTEGER) AS first_absolute_day,
            CAST(last_absolute_day AS INTEGER) AS last_absolute_day,
            CAST(days_in_year AS SMALLINT) AS days_in_year,
            CAST(is_leap_year AS BOOLEAN) AS is_leap_year,
            CAST(months_in_year AS SMALLINT) AS months_in_year,
            CAST(rosh_hashanah_weekday_sunday_0 AS SMALLINT)
                AS rosh_hashanah_weekday_sunday_0,
            CAST(long_cheshvan AS BOOLEAN) AS long_cheshvan,
            CAST(short_kislev AS BOOLEAN) AS short_kislev
        """,
    },
    "core_month": {
        "order": "hebrew_year, hebrew_month_tishrei_index",
        "select": """
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(hebrew_month AS SMALLINT) AS hebrew_month,
            CAST(hebrew_month_tishrei_index AS SMALLINT)
                AS hebrew_month_tishrei_index,
            CAST(hebrew_month_name AS VARCHAR) AS hebrew_month_name,
            CAST(first_absolute_day AS INTEGER) AS first_absolute_day,
            CAST(last_absolute_day AS INTEGER) AS last_absolute_day,
            CAST(days_in_month AS SMALLINT) AS days_in_month
        """,
    },
    "core_day": {
        "order": "absolute_day",
        "select": """
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(hebrew_month AS SMALLINT) AS hebrew_month,
            CAST(hebrew_month_tishrei_index AS SMALLINT)
                AS hebrew_month_tishrei_index,
            CAST(hebrew_month_name AS VARCHAR) AS hebrew_month_name,
            CAST(hebrew_day AS SMALLINT) AS hebrew_day,
            CAST(weekday_sunday_0 AS SMALLINT) AS weekday_sunday_0,
            CAST(hebrew_date_en AS VARCHAR) AS hebrew_date_en,
            CAST(hebrew_date_he AS VARCHAR) AS hebrew_date_he,
            CAST(hebrew_date_ashkenazi AS VARCHAR) AS hebrew_date_ashkenazi,
            CAST(hebrew_date_gematria AS VARCHAR) AS hebrew_date_gematria,
            CAST(gregorian_year_signed AS INTEGER) AS gregorian_year_signed,
            CAST(gregorian_era AS VARCHAR) AS gregorian_era,
            CAST(gregorian_year_of_era AS INTEGER) AS gregorian_year_of_era,
            CAST(gregorian_month AS SMALLINT) AS gregorian_month,
            CAST(gregorian_day AS SMALLINT) AS gregorian_day,
            CAST(gregorian_date_text AS VARCHAR) AS gregorian_date_text,
            TRY_CAST(powerbi_date AS DATE) AS powerbi_date
        """,
    },
    "core_day_schedule": {
        "order": "absolute_day, schedule",
        "select": """
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(schedule AS VARCHAR) AS schedule,
            CAST(hallel AS SMALLINT) AS hallel,
            CAST(tachanun_json AS VARCHAR) AS tachanun_json,
            CAST(tachanun_supported AS BOOLEAN) AS tachanun_supported,
            CAST(tachanun_error AS VARCHAR) AS tachanun_error,
            CAST(eruv_tavshilin AS BOOLEAN) AS eruv_tavshilin
        """,
    },
    "core_event_occurrence": {
        "order": "absolute_day, schedule, occurrence_id",
        "select": """
            CAST(occurrence_id AS VARCHAR) AS occurrence_id,
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(schedule AS VARCHAR) AS schedule,
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(event_class AS VARCHAR) AS event_class,
            CAST(event_description AS VARCHAR) AS event_description,
            CAST(event_basename AS VARCHAR) AS event_basename,
            CAST(event_flags AS INTEGER) AS event_flags,
            CAST(title_en AS VARCHAR) AS title_en,
            CAST(title_he AS VARCHAR) AS title_he,
            CAST(title_ashkenazi AS VARCHAR) AS title_ashkenazi,
            CAST(url AS VARCHAR) AS url,
            CAST(raw_event_json AS VARCHAR) AS raw_event_json
        """,
    },
    "core_parasha_occurrence": {
        "order": "absolute_day, schedule, occurrence_id",
        "select": """
            CAST(occurrence_id AS VARCHAR) AS occurrence_id,
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(schedule AS VARCHAR) AS schedule,
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(parasha AS VARCHAR[]) AS parasha,
            CAST(is_combined AS BOOLEAN) AS is_combined,
            CAST(title_en AS VARCHAR) AS title_en,
            CAST(title_he AS VARCHAR) AS title_he,
            CAST(title_ashkenazi AS VARCHAR) AS title_ashkenazi,
            CAST(basename AS VARCHAR) AS basename,
            CAST(url AS VARCHAR) AS url,
            CAST(raw_event_json AS VARCHAR) AS raw_event_json
        """,
    },
    "core_leyning_occurrence": {
        "order": "absolute_day, schedule, reading_index, occurrence_id",
        "select": """
            CAST(occurrence_id AS VARCHAR) AS occurrence_id,
            CAST(hebrew_year AS INTEGER) AS hebrew_year,
            CAST(schedule AS VARCHAR) AS schedule,
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(reading_index AS SMALLINT) AS reading_index,
            CAST(reading_type AS VARCHAR) AS reading_type,
            CAST(name_en AS VARCHAR) AS name_en,
            CAST(name_he AS VARCHAR) AS name_he,
            CAST(summary AS VARCHAR) AS summary,
            CAST(summary_he AS VARCHAR) AS summary_he,
            CAST(summary_ashkenazi AS VARCHAR) AS summary_ashkenazi,
            CAST(parasha_json AS VARCHAR) AS parasha_json,
            CAST(parasha_num_json AS VARCHAR) AS parasha_num_json,
            CAST(raw_reading_json AS VARCHAR) AS raw_reading_json,
            CAST(raw_reading_json_he AS VARCHAR) AS raw_reading_json_he,
            CAST(raw_reading_json_ashkenazi AS VARCHAR)
                AS raw_reading_json_ashkenazi,
            CAST(source_payload_sha256 AS VARCHAR) AS source_payload_sha256
        """,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sql_literal(path: Path) -> str:
    return "'" + str(path.resolve()).replace("\\", "/").replace("'", "''") + "'"


def package_version(package_name: str) -> str:
    package_path = SCRIPT_DIR / "node_modules" / Path(*package_name.split("/")) / "package.json"
    if not package_path.exists():
        raise RuntimeError(
            f"{package_name} is not installed; run npm install in {SCRIPT_DIR}"
        )
    return str(load_json(package_path)["version"])


def verify_dependencies(contract: dict[str, Any]) -> dict[str, str]:
    versions = {
        package: package_version(package)
        for package in contract["sourcePackages"]
    }
    for package, expected in contract["sourcePackages"].items():
        if versions[package] != expected:
            raise RuntimeError(
                f"{package} version {versions[package]} does not match contract {expected}"
            )
    return versions


def export_parquet(connection: duckdb.DuckDBPyConnection, raw_dir: Path, artifact_dir: Path) -> None:
    for table_name, table in TABLES.items():
        input_path = raw_dir / f"{table_name}.ndjson"
        output_path = artifact_dir / f"{table_name}.parquet"
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT {table["select"]}
            FROM read_json_auto(
                {sql_literal(input_path)},
                format = 'newline_delimited',
                union_by_name = true
            )
            """
        )
        connection.execute(
            f"""
            COPY (
                SELECT *
                FROM {table_name}
                ORDER BY {table["order"]}
            )
            TO {sql_literal(output_path)}
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                ROW_GROUP_SIZE 100000
            )
            """
        )


def scalar(connection: duckdb.DuckDBPyConnection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def validate_tables(
    connection: duckdb.DuckDBPyConnection,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    expected_years = end_year - start_year + 1
    year_count = scalar(connection, "SELECT count(*) FROM core_year")
    if year_count != expected_years:
        raise RuntimeError(f"expected {expected_years} years, found {year_count}")

    expected_days = scalar(connection, "SELECT sum(days_in_year) FROM core_year")
    day_count = scalar(connection, "SELECT count(*) FROM core_day")
    distinct_days = scalar(
        connection, "SELECT count(DISTINCT absolute_day) FROM core_day"
    )
    minimum_day, maximum_day = connection.execute(
        "SELECT min(absolute_day), max(absolute_day) FROM core_day"
    ).fetchone()
    if day_count != expected_days or distinct_days != day_count:
        raise RuntimeError(
            f"day spine mismatch: rows={day_count}, distinct={distinct_days}, "
            f"expected={expected_days}"
        )
    if maximum_day - minimum_day + 1 != day_count:
        raise RuntimeError("absolute_day spine contains a gap")

    invalid_year_lengths = scalar(
        connection,
        """
        SELECT count(*)
        FROM core_year
        WHERE days_in_year NOT IN (353, 354, 355, 383, 384, 385)
        """,
    )
    invalid_month_lengths = scalar(
        connection,
        """
        SELECT count(*)
        FROM core_month
        WHERE days_in_month NOT IN (29, 30)
        """,
    )
    if invalid_year_lengths or invalid_month_lengths:
        raise RuntimeError(
            f"invalid calendar lengths: years={invalid_year_lengths}, "
            f"months={invalid_month_lengths}"
        )

    for table_name in (
        "core_event_occurrence",
        "core_parasha_occurrence",
        "core_leyning_occurrence",
    ):
        rows, unique_ids = connection.execute(
            f"SELECT count(*), count(DISTINCT occurrence_id) FROM {table_name}"
        ).fetchone()
        if rows != unique_ids:
            raise RuntimeError(
                f"{table_name} contains {rows - unique_ids} duplicate occurrence IDs"
            )

    day_schedule_rows, day_schedule_keys = connection.execute(
        """
        SELECT count(*), count(DISTINCT (absolute_day, schedule))
        FROM core_day_schedule
        """
    ).fetchone()
    if day_schedule_rows != day_count * 2 or day_schedule_keys != day_schedule_rows:
        raise RuntimeError(
            "core_day_schedule must contain exactly one row per day and schedule"
        )

    return {
        "core_year": {
            "rows": year_count,
            "first_year": scalar(connection, "SELECT min(hebrew_year) FROM core_year"),
            "last_year": scalar(connection, "SELECT max(hebrew_year) FROM core_year"),
        },
        "core_month": {
            "rows": scalar(connection, "SELECT count(*) FROM core_month"),
        },
        "core_day": {
            "rows": day_count,
            "first_absolute_day": minimum_day,
            "last_absolute_day": maximum_day,
            "native_powerbi_dates": scalar(
                connection, "SELECT count(powerbi_date) FROM core_day"
            ),
        },
        "core_day_schedule": {
            "rows": day_schedule_rows,
        },
        "core_event_occurrence": {
            "rows": scalar(
                connection, "SELECT count(*) FROM core_event_occurrence"
            ),
        },
        "core_parasha_occurrence": {
            "rows": scalar(
                connection, "SELECT count(*) FROM core_parasha_occurrence"
            ),
        },
        "core_leyning_occurrence": {
            "rows": scalar(
                connection, "SELECT count(*) FROM core_leyning_occurrence"
            ),
        },
    }


def build_partition(start_year: int, end_year: int, output_root: Path) -> Path:
    contract = load_json(CONTRACT_PATH)
    first = int(contract["hebrewYearRange"]["first"])
    last = int(contract["hebrewYearRange"]["last"])
    if start_year < first or end_year > last or end_year < start_year:
        raise ValueError(f"year range must be ordered and within {first}-{last}")

    block_name = f"block={start_year:04d}-{end_year:04d}"
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if (output_root / "manifest.json").exists():
        raise FileExistsError(
            f"{output_root} is already finalized; corpus-v1 cannot accept new partitions"
        )
    final_dir = output_root / block_name
    if final_dir.exists():
        raise FileExistsError(
            f"{final_dir} already exists; immutable partitions cannot be overwritten"
        )

    versions = verify_dependencies(contract)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".staging-{block_name}-", dir=output_root)
    )
    raw_dir = staging_root / "raw"
    artifact_dir = staging_root / "artifact"
    raw_dir.mkdir()
    artifact_dir.mkdir()
    database_path = staging_root / "build.duckdb"

    try:
        subprocess.run(
            [
                "node",
                str(GENERATOR_PATH),
                "--start-year",
                str(start_year),
                "--end-year",
                str(end_year),
                "--output-dir",
                str(raw_dir),
            ],
            cwd=SCRIPT_DIR,
            check=True,
        )
        with duckdb.connect(str(database_path)) as connection:
            export_parquet(connection, raw_dir, artifact_dir)
            validation = validate_tables(connection, start_year, end_year)

        files = {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(artifact_dir.glob("*.parquet"))
        }
        manifest = {
            "corpus_version": contract["corpusVersion"],
            "immutability": "core partition; never overwrite",
            "block": block_name.removeprefix("block="),
            "start_year": start_year,
            "end_year": end_year,
            "source_packages": versions,
            "duckdb_version": duckdb.__version__,
            "source_hashes": {
                path.name: sha256(path)
                for path in IMMUTABLE_SOURCE_PATHS
            },
            "validation": validation,
            "files": files,
            "attribution": "Hebcal.com; generated content licensed CC BY 4.0",
        }
        manifest_path = artifact_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        provenance = {
            "created_utc": datetime.now(UTC).isoformat(),
            "content_manifest_sha256": sha256(manifest_path),
            "population_tool": f"DuckDB {duckdb.__version__}",
        }
        (artifact_dir / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(artifact_dir, final_dir)
    except BaseException:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    else:
        shutil.rmtree(staging_root, ignore_errors=True)
    return final_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = build_partition(args.start_year, args.end_year, args.output_root)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
