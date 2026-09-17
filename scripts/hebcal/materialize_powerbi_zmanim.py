#!/usr/bin/env python3
"""Materialize immutable Milwaukee Zmanim rows for the Power BI model."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import duckdb


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "hebcal" / "zmanim-milwaukee-v1"
DEFAULT_COMPATIBILITY = (
    REPO_ROOT
    / "data"
    / "hebcal"
    / "powerbi-compatibility-v1"
    / "hebcal_compatibility.parquet"
)
START_DATE = "1900-03-01"
END_DATE = "2240-09-16"  # 29 Elul 6000
MATERIALIZATION_VERSION = "zmanim-milwaukee-v1"
LEGACY_MAX_DIFFERENCE_SECONDS = 3
LOCATION = {
    "city": "Milwaukee",
    "zip": "53216",
    "tzid": "America/Chicago",
    "latitude": 43.088013,
    "longitude": -87.977046,
    "elevation": 680,
}
VARIABLES = (
    "alotHaShachar",
    "beinHaShmashos",
    "chatzot",
    "chatzotNight",
    "dawn",
    "dayLength",
    "dusk",
    "minchaGedola",
    "minchaKetana",
    "misheyakir",
    "misheyakirMachmir",
    "plagHaMincha",
    "shaahZmanis",
    "sofZmanShma",
    "sofZmanShmaMGA",
    "sofZmanShmaMGA16Point1",
    "sofZmanTfilla",
    "sofZmanTfillaMGA",
    "sunrise",
    "sunset",
    "tzeit42min",
    "tzeit50min",
    "tzeit7083deg",
    "tzeit72min",
    "tzeit85deg",
)
CALCULATED_VARIABLES = tuple(
    variable for variable in VARIABLES if variable not in {"dayLength", "shaahZmanis"}
)


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_exclusive(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _long_source_sql(csv_path: Path) -> str:
    rows = []
    for variable in VARIABLES:
        if variable in CALCULATED_VARIABLES:
            value = f'try_cast("{variable}" AS TIMESTAMP)'
            elevation = f'try_cast("{variable}_Elevation" AS TIMESTAMP)'
        else:
            value = "NULL::TIMESTAMP"
            elevation = "NULL::TIMESTAMP"
        rows.append(
            'SELECT cast(Date AS DATE) "Date", '
            f"'{variable}' \"Variable\", {value} \"Value\", "
            f'{elevation} "Value_Elevation" '
            f"FROM read_csv({sql_literal(csv_path)}, header=true, all_varchar=true)"
        )
    return "\nUNION ALL\n".join(rows)


def materialize(
    output_root: Path,
    start_date: str = START_DATE,
    end_date: str = END_DATE,
    compatibility_path: Path | None = DEFAULT_COMPATIBILITY,
) -> Path:
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"immutable output already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    parquet_path = output_root / "zmanim.parquet"
    manifest_path = output_root / "manifest.json"

    try:
        with tempfile.TemporaryDirectory(prefix="zmanim-materialize-") as directory:
            csv_path = Path(directory) / "zmanim.csv"
            subprocess.run(
                [
                    "node",
                    str(SCRIPT_DIR / "generate_zmanim_csv.mjs"),
                    start_date,
                    end_date,
                    str(csv_path),
                ],
                cwd=SCRIPT_DIR,
                check=True,
            )
            long_sql = _long_source_sql(csv_path)
            with duckdb.connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                        WITH base AS ({long_sql})
                        SELECT
                            "Date",
                            "Variable",
                            "Value",
                            "Value_Elevation",
                            lag("Value", 1) OVER by_variable AS "Value_Yesterday",
                            lag("Value", 7) OVER by_variable AS "Value_OneWeekAgo"
                        FROM base
                        WINDOW by_variable AS (
                            PARTITION BY "Variable" ORDER BY "Date"
                        )
                        ORDER BY "Date", "Variable"
                    ) TO {sql_literal(parquet_path)} (
                        FORMAT PARQUET,
                        COMPRESSION ZSTD,
                        ROW_GROUP_SIZE 122880
                    )
                    """
                )
                validation = connection.execute(
                    f"""
                    SELECT
                        count(*) row_count,
                        count(DISTINCT "Date") date_count,
                        count(DISTINCT "Variable") variable_count,
                        min("Date") min_date,
                        max("Date") max_date,
                        count(*) FILTER (WHERE "Value" IS NOT NULL) populated_values
                    FROM read_parquet({sql_literal(parquet_path)})
                    """
                ).fetchone()
                expected_rows = validation[1] * len(VARIABLES)
                if validation[0] != expected_rows or validation[2] != len(VARIABLES):
                    raise RuntimeError("Zmanim output is not a complete date-variable grid")
                expected_populated = validation[1] * len(CALCULATED_VARIABLES)
                if validation[5] != expected_populated:
                    raise RuntimeError("Zmanim output has unexpected null values")

                overlap = None
                if compatibility_path and compatibility_path.is_file():
                    unions = " UNION ALL ".join(
                        f'SELECT cast("Date" AS DATE) "Date", '
                        f'\'{variable}\' "Variable", '
                        f'cast("{variable}" AS TIMESTAMP) "Value" FROM '
                        f'read_parquet({sql_literal(compatibility_path)}) '
                        f'WHERE "{variable}" IS NOT NULL'
                        for variable in CALCULATED_VARIABLES
                    )
                    overlap = connection.execute(
                        f"""
                        WITH legacy AS ({unions}),
                        landed AS (
                            SELECT "Date", "Variable", "Value"
                            FROM read_parquet({sql_literal(parquet_path)})
                        )
                        SELECT
                            count(*) compared_rows,
                            max(abs(epoch(legacy."Value") - epoch(landed."Value"))) max_seconds
                        FROM legacy
                        JOIN landed USING ("Date", "Variable")
                        """
                    ).fetchone()
                    if (
                        overlap[0] == 0
                        or overlap[1] > LEGACY_MAX_DIFFERENCE_SECONDS
                    ):
                        raise RuntimeError(
                            f"legacy overlap differs by {overlap[1]} seconds"
                        )

        manifest = {
            "materialization_version": MATERIALIZATION_VERSION,
            "source": {
                "algorithm": "@hebcal/core Zmanim NOAA calculations",
                "generator": "scripts/hebcal/generate_zmanim_csv.mjs",
                "generator_sha256": sha256(SCRIPT_DIR / "generate_zmanim_csv.mjs"),
                "materializer_sha256": sha256(Path(__file__)),
                "package_lock_sha256": sha256(SCRIPT_DIR / "package-lock.json"),
            },
            "location": LOCATION,
            "date_range": {"start": start_date, "end": end_date},
            "variables": list(VARIABLES),
            "file": {
                "path": "zmanim.parquet",
                "bytes": parquet_path.stat().st_size,
                "sha256": sha256(parquet_path),
            },
            "validation": {
                "rows": validation[0],
                "dates": validation[1],
                "variables": validation[2],
                "min_date": str(validation[3]),
                "max_date": str(validation[4]),
                "populated_values": validation[5],
                "legacy_overlap_rows": overlap[0] if overlap else None,
                "legacy_max_difference_seconds": overlap[1] if overlap else None,
                "legacy_tolerance_seconds": LEGACY_MAX_DIFFERENCE_SECONDS,
            },
        }
        write_json_exclusive(manifest_path, manifest)
        return manifest_path
    except Exception:
        for path in (manifest_path, parquet_path):
            if path.exists():
                path.unlink()
        if output_root.exists() and not any(output_root.iterdir()):
            output_root.rmdir()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end", default=END_DATE)
    parser.add_argument("--compatibility", type=Path, default=DEFAULT_COMPATIBILITY)
    args = parser.parse_args()
    manifest = materialize(
        args.output_root, args.start, args.end, args.compatibility
    )
    print(manifest)


if __name__ == "__main__":
    main()
