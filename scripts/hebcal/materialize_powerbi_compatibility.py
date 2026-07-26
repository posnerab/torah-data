#!/usr/bin/env python3
"""Materialize the loaded legacy Hebcal table as an immutable compatibility v1.

The one-time source snapshot is exported from the validated Power BI Desktop
model by scripts/powerbi/Export-HebcalCompatibilitySnapshot.ps1. This command
reads that snapshot, verifies its exact 87-column contract, and writes a
deterministic Parquet artifact. It never reads or modifies corpus-v1, and it
has no overwrite option.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "hebcal" / "powerbi-compatibility-v1"

MATERIALIZATION_VERSION = "powerbi-compatibility-v1"
OUTPUT_FILE_NAME = "hebcal_compatibility.parquet"
SOURCE_FILE_NAME = "hebcal_compatibility.jsonl"

OFFICIAL_SOURCE_JSONL_SHA256 = (
    "df72a72b36e2a75e0c6cb6d5ec4dc7956f0a412a629dc8acfc861a16057c5e47"
)
OFFICIAL_SOURCE_SCHEMA_SHA256 = (
    "288aa02dc36367cce18b1653b9ab700263423347e85e4f4671c8973e51ed5aaa"
)
OFFICIAL_VALIDATION = {
    "rows": 18_987,
    "unique_dates": 18_987,
    "first_date": "2023-09-16 00:00:00",
    "last_date": "2075-09-09 00:00:00",
    "first_hebrew_year": 5_784,
    "last_hebrew_year": 5_835,
    "zmanim_rows": 1_095,
    "first_zmanim_date": "2025-01-01 00:00:00",
    "last_zmanim_date": "2027-12-31 00:00:00",
}

EXPECTED_COLUMNS = (
    ("Date", "dateTime"),
    ("Hebrew Date", "string"),
    ("Category", "string"),
    ("Hebrew Title", "string"),
    ("Link", "string"),
    ("Description", "string"),
    ("Yom Tov?", "string"),
    ("Omer Count", "string"),
    ("Sefira Transliteration", "string"),
    ("Sefira English", "string"),
    ("Torah Reading", "string"),
    ("Haftarah", "string"),
    ("Maftir", "string"),
    ("First Aliyah", "string"),
    ("Second Aliyah", "string"),
    ("Third Aliyah", "string"),
    ("Fourth Aliyah", "string"),
    ("Fifth Aliyah", "string"),
    ("Sixth Aliyah", "string"),
    ("Seventh Aliyah", "string"),
    ("Haftarah Sephardim", "string"),
    ("Occasion", "string"),
    ("Haftarah Reason", "string"),
    ("Maftir Reason", "string"),
    ("Hebrew Year", "int64"),
    ("Hebrew Day of Month", "int64"),
    ("Hebrew Month", "string"),
    ("Hebrew Month Year", "string"),
    ("Hebrew Month Year Order", "string"),
    ("Day Name", "string"),
    ("Hebrew Month Number", "int64"),
    ("Hebrew Month Number Tishrei Start", "int64"),
    ("Day of the Omer", "int64"),
    ("Days in Hebrew Month", "int64"),
    ("Parasha M-Th", "string"),
    ("Torah Reading M-Th", "string"),
    ("First Aliyah M-Th", "string"),
    ("Second Aliyah M-Th", "string"),
    ("Third Aliyah M-Th", "string"),
    ("Parasha", "string"),
    ("Sefer", "string"),
    ("Book", "string"),
    ("Index_Parasha", "int64"),
    ("Haftarah.1", "string"),
    ("Haftarah.2", "string"),
    ("Haftarah.3", "string"),
    ("Index_Haftarah", "string"),
    ("Hebrew Month Day", "string"),
    ("Index_Leap", "int64"),
    ("Index_Common", "int64"),
    ("city", "string"),
    ("tzid", "string"),
    ("latitude", "double"),
    ("longitude", "double"),
    ("chatzotNight", "dateTime"),
    ("alotHaShachar", "dateTime"),
    ("misheyakir", "dateTime"),
    ("misheyakirMachmir", "dateTime"),
    ("dawn", "dateTime"),
    ("sunrise", "dateTime"),
    ("sofZmanShmaMGA16Point1", "dateTime"),
    ("sofZmanShmaMGA", "dateTime"),
    ("sofZmanShma", "dateTime"),
    ("sofZmanTfillaMGA16Point1", "dateTime"),
    ("sofZmanTfillaMGA", "dateTime"),
    ("sofZmanTfilla", "dateTime"),
    ("chatzot", "dateTime"),
    ("minchaGedola", "dateTime"),
    ("minchaKetana", "dateTime"),
    ("plagHaMincha", "dateTime"),
    ("sunset", "dateTime"),
    ("beinHaShmashos", "dateTime"),
    ("dusk", "dateTime"),
    ("tzeit7083deg", "dateTime"),
    ("tzeit85deg", "dateTime"),
    ("tzeit42min", "dateTime"),
    ("tzeit50min", "dateTime"),
    ("tzeit72min", "dateTime"),
    ("Other", "string"),
    ("Major", "string"),
    ("Fast", "string"),
    ("Special Shabbos", "string"),
    ("Minor", "string"),
    ("Shabbos Mevorchim", "string"),
    ("Rosh Chodesh", "string"),
    ("Doubled", "boolean"),
    ("Jewish Holidays", "string"),
)

DUCKDB_TYPES = {
    "string": "VARCHAR",
    "int64": "BIGINT",
    "double": "DOUBLE",
    "boolean": "BOOLEAN",
    "dateTime": "TIMESTAMP",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _verify_snapshot(
    snapshot_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    schema_path = snapshot_root / "schema.json"
    provenance_path = snapshot_root / "provenance.json"
    source_path = snapshot_root / SOURCE_FILE_NAME
    for path in (schema_path, provenance_path, source_path):
        if not path.is_file():
            raise FileNotFoundError(f"compatibility source is missing {path.name}")

    schema = load_json(schema_path)
    provenance = load_json(provenance_path)
    schema_hash = sha256(schema_path)
    source_hash = sha256(source_path)
    if schema.get("snapshot_version") != "hebcal-compatibility-source-v1":
        raise RuntimeError("unexpected compatibility snapshot version")
    if schema.get("table_name") != "Hebcal":
        raise RuntimeError("compatibility snapshot must come from table Hebcal")
    if provenance.get("schema_sha256") != schema_hash:
        raise RuntimeError("snapshot provenance does not match schema.json")
    if provenance.get("source_jsonl_sha256") != source_hash:
        raise RuntimeError("snapshot provenance does not match the JSONL source")

    columns = schema.get("columns")
    if not isinstance(columns, list):
        raise RuntimeError("snapshot schema has no columns")
    actual_contract = tuple(
        (column.get("name"), column.get("data_type")) for column in columns
    )
    if actual_contract != EXPECTED_COLUMNS:
        raise RuntimeError("snapshot does not match the exact 87-column contract")
    if any(column.get("source_column") != column.get("name") for column in columns):
        raise RuntimeError("snapshot source-column names are not identity mappings")
    if schema.get("row_count") is None or int(schema["row_count"]) <= 0:
        raise RuntimeError("snapshot schema has no positive row count")
    exporter_hash = schema.get("exporter_script_sha256")
    if (
        not isinstance(exporter_hash, str)
        or len(exporter_hash) != 64
        or any(character not in "0123456789abcdef" for character in exporter_hash)
    ):
        raise RuntimeError("snapshot has no valid exporter script checksum")
    return schema, provenance, schema_hash, source_hash


def _json_columns_sql() -> str:
    members = ", ".join(
        f"{sql_literal(name)}: {sql_literal(DUCKDB_TYPES[data_type])}"
        for name, data_type in EXPECTED_COLUMNS
    )
    return "{" + members + "}"


def _create_source_view(
    connection: duckdb.DuckDBPyConnection, source_path: Path
) -> None:
    connection.execute(
        f"""
        CREATE TEMP VIEW source_compatibility AS
        SELECT *
        FROM read_json(
            {sql_literal(source_path)},
            format = 'newline_delimited',
            columns = {_json_columns_sql()}
        )
        """
    )


def _validate_source(
    connection: duckdb.DuckDBPyConnection, expected_rows: int
) -> dict[str, Any]:
    (
        rows,
        unique_dates,
        first_date,
        last_date,
        first_hebrew_year,
        last_hebrew_year,
        null_dates,
        null_hebrew_dates,
    ) = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT "Date"),
            min("Date"),
            max("Date"),
            min("Hebrew Year"),
            max("Hebrew Year"),
            count(*) FILTER (WHERE "Date" IS NULL),
            count(*) FILTER (WHERE "Hebrew Date" IS NULL)
        FROM source_compatibility
        """
    ).fetchone()
    if rows != expected_rows:
        raise RuntimeError(
            f"snapshot row count mismatch: schema={expected_rows}, data={rows}"
        )
    if rows != unique_dates or null_dates or null_hebrew_dates:
        raise RuntimeError(
            "compatibility grain failed: "
            f"rows={rows}, dates={unique_dates}, "
            f"null_dates={null_dates}, null_hebrew_dates={null_hebrew_dates}"
        )

    noncontiguous_dates = connection.execute(
        """
        SELECT count(*)
        FROM (
            SELECT
                "Date",
                lag("Date") OVER (ORDER BY "Date") AS prior_date
            FROM source_compatibility
        )
        WHERE prior_date IS NOT NULL
          AND date_diff('day', prior_date, "Date") <> 1
        """
    ).fetchone()[0]
    if noncontiguous_dates:
        raise RuntimeError(
            f"compatibility snapshot has {noncontiguous_dates} date gaps"
        )

    zmanim_rows, first_zmanim_date, last_zmanim_date = connection.execute(
        """
        SELECT
            count(*) FILTER (WHERE city IS NOT NULL),
            min("Date") FILTER (WHERE city IS NOT NULL),
            max("Date") FILTER (WHERE city IS NOT NULL)
        FROM source_compatibility
        """
    ).fetchone()
    inconsistent_zmanim = connection.execute(
        """
        SELECT count(*)
        FROM source_compatibility
        WHERE (city IS NULL) <> (tzid IS NULL)
           OR (city IS NULL) <> (latitude IS NULL)
           OR (city IS NULL) <> (longitude IS NULL)
           OR (city IS NULL) <> (sunrise IS NULL)
           OR (city IS NULL) <> (sunset IS NULL)
        """
    ).fetchone()[0]
    if inconsistent_zmanim:
        raise RuntimeError(
            f"compatibility snapshot has {inconsistent_zmanim} partial zmanim rows"
        )

    return {
        "rows": int(rows),
        "unique_dates": int(unique_dates),
        "first_date": str(first_date),
        "last_date": str(last_date),
        "first_hebrew_year": int(first_hebrew_year),
        "last_hebrew_year": int(last_hebrew_year),
        "date_gaps": int(noncontiguous_dates),
        "zmanim_rows": int(zmanim_rows),
        "first_zmanim_date": str(first_zmanim_date),
        "last_zmanim_date": str(last_zmanim_date),
        "partial_zmanim_rows": int(inconsistent_zmanim),
    }


def _validate_official_snapshot(
    source_hash: str, schema_hash: str, validation: dict[str, Any]
) -> bool:
    if (
        source_hash != OFFICIAL_SOURCE_JSONL_SHA256
        or schema_hash != OFFICIAL_SOURCE_SCHEMA_SHA256
    ):
        return False
    for key, expected in OFFICIAL_VALIDATION.items():
        actual = validation.get(key)
        if actual != expected:
            raise RuntimeError(
                f"official compatibility {key} mismatch: "
                f"expected={expected}, actual={actual}"
            )
    return True


def _validate_round_trip(
    connection: duckdb.DuckDBPyConnection, output_path: Path
) -> dict[str, int]:
    selected_columns = ", ".join(
        sql_identifier(name) for name, _ in EXPECTED_COLUMNS
    )
    output_relation = (
        "read_parquet("
        f"{sql_literal(output_path)}, "
        "hive_partitioning = false"
        ")"
    )
    source_minus_output = connection.execute(
        f"""
        SELECT count(*)
        FROM (
            (SELECT {selected_columns} FROM source_compatibility)
            EXCEPT ALL
            (SELECT {selected_columns} FROM {output_relation})
        )
        """
    ).fetchone()[0]
    output_minus_source = connection.execute(
        f"""
        SELECT count(*)
        FROM (
            (SELECT {selected_columns} FROM {output_relation})
            EXCEPT ALL
            (SELECT {selected_columns} FROM source_compatibility)
        )
        """
    ).fetchone()[0]
    if source_minus_output or output_minus_source:
        raise RuntimeError(
            "compatibility Parquet changed source values: "
            f"source_minus_output={source_minus_output}, "
            f"output_minus_source={output_minus_source}"
        )
    return {
        "source_minus_output_rows": int(source_minus_output),
        "output_minus_source_rows": int(output_minus_source),
    }


def _parquet_columns(path: Path) -> list[dict[str, str]]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_literal(path)})"
        ).fetchall()
    return [
        {"name": row[0], "type": row[1], "nullable": row[2]}
        for row in rows
    ]


def materialize(snapshot_root: Path, output_root: Path) -> Path:
    snapshot_root = snapshot_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(
            f"{output_root} already exists; {MATERIALIZATION_VERSION} cannot be rewritten"
        )
    if output_root == snapshot_root or snapshot_root in output_root.parents:
        raise ValueError("compatibility output cannot be inside its source snapshot")

    schema, source_provenance, schema_hash, source_hash = _verify_snapshot(
        snapshot_root
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}-",
            dir=output_root.parent,
        )
    )
    artifact_root = workspace / "artifact"
    artifact_root.mkdir()
    try:
        duckdb_temp = workspace / "duckdb-temp"
        duckdb_temp.mkdir()
        output_path = artifact_root / OUTPUT_FILE_NAME
        with duckdb.connect() as connection:
            connection.execute("SET threads = 1")
            connection.execute("SET default_collation = ''")
            connection.execute("SET preserve_insertion_order = true")
            connection.execute(
                f"SET temp_directory = {sql_literal(duckdb_temp)}"
            )
            _create_source_view(
                connection, snapshot_root / SOURCE_FILE_NAME
            )
            validation = _validate_source(
                connection, int(schema["row_count"])
            )
            official_baseline_verified = _validate_official_snapshot(
                source_hash, schema_hash, validation
            )
            selected_columns = ", ".join(
                sql_identifier(name) for name, _ in EXPECTED_COLUMNS
            )
            connection.execute(
                f"""
                COPY (
                    SELECT {selected_columns}
                    FROM source_compatibility
                    ORDER BY "Date"
                )
                TO {sql_literal(output_path)}
                (
                    FORMAT PARQUET,
                    COMPRESSION ZSTD,
                    ROW_GROUP_SIZE 100000
                )
                """
            )
            validation.update(_validate_round_trip(connection, output_path))

        with duckdb.connect() as connection:
            output_validation = _validate_source_from_parquet(
                connection, output_path, int(schema["row_count"])
            )
        for key, value in output_validation.items():
            if validation.get(key) != value:
                raise RuntimeError(
                    "landed compatibility Parquet validation differs from "
                    f"source for {key}: "
                    f"source={validation.get(key)}, output={value}"
                )

        manifest = {
            "materialization_version": MATERIALIZATION_VERSION,
            "status": "complete-immutable-derived",
            "source": {
                "kind": "power-bi-semantic-model-snapshot",
                "table_name": schema["table_name"],
                "snapshot_version": schema["snapshot_version"],
                "source_jsonl_sha256": source_hash,
                "source_schema_sha256": schema_hash,
                "source_exporter_script_sha256": (
                    schema["exporter_script_sha256"]
                ),
                "source_tmdl_sha256": schema["tmdl_sha256"],
                "source_dax_query_sha256": schema["dax_query_sha256"],
            },
            "builder": {
                "script_sha256": sha256(Path(__file__).resolve()),
                "duckdb_version": duckdb.__version__,
            },
            "grain": ["Date"],
            "files": {
                OUTPUT_FILE_NAME: {
                    "bytes": output_path.stat().st_size,
                    "sha256": sha256(output_path),
                    "rows": validation["rows"],
                    "columns": _parquet_columns(output_path),
                }
            },
            "validation": validation,
            "official_legacy_baseline_verified": official_baseline_verified,
            "scope": {
                "purpose": "exact wide-table cutover shim",
                "normalized_all_years_data_location": (
                    "corpus-v1 and normalized Power BI projections"
                ),
                "includes_loaded_zmanim_overlay": True,
            },
            "immutability": {
                "overwrite_existing_output": False,
                "source_snapshot_modified": False,
                "core_corpus_modified": False,
                "changed_projection_requires_new_version": True,
            },
            "attribution": "Hebcal.com; generated content licensed CC BY 4.0",
        }
        manifest_path = artifact_root / "manifest.json"
        write_json_exclusive(manifest_path, manifest)
        provenance = {
            "created_utc": datetime.now(UTC).isoformat(),
            "content_manifest_sha256": sha256(manifest_path),
            "materialization_id": f"sha256:{sha256(manifest_path)}",
            "materialization_tool": f"DuckDB {duckdb.__version__}",
            "source_exported_utc": source_provenance.get("exported_utc"),
            "source_database": source_provenance.get("database"),
        }
        write_json_exclusive(artifact_root / "provenance.json", provenance)

        if output_root.exists():
            raise FileExistsError(
                f"{output_root} appeared during build; refusing to overwrite it"
            )
        artifact_root.rename(output_root)
        return output_root / "manifest.json"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _validate_source_from_parquet(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    expected_rows: int,
) -> dict[str, Any]:
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW source_compatibility AS
        SELECT *
        FROM read_parquet(
            {sql_literal(path)},
            hive_partitioning = false
        )
        """
    )
    return _validate_source(connection, expected_rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        required=True,
        help="one-time source directory written by the Power BI exporter",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"new destination that must not exist (default: {DEFAULT_OUTPUT_ROOT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(materialize(args.snapshot_root, args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
