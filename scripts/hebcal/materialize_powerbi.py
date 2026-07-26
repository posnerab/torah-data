#!/usr/bin/env python3
"""Materialize the immutable corpus-v1 Power BI boundary once.

The source corpus is opened read-only. The destination must not exist, and this
command deliberately has no overwrite or force option. A changed projection is
a new materialization version, not a rewrite of powerbi-v1.
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
DEFAULT_CORPUS_ROOT = REPO_ROOT / "data" / "hebcal" / "corpus-v1"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "hebcal" / "powerbi-v1"

MATERIALIZATION_VERSION = "powerbi-v1"
SOURCE_TABLE_FILES = (
    "core_day.parquet",
    "core_day_schedule.parquet",
    "core_event_occurrence.parquet",
)
OUTPUT_TABLE_FILES = (
    "hebrew_day_schedule.parquet",
    "hebcal_event_definition.parquet",
    "hebcal_event_occurrence.parquet",
)
EVENT_DEFINITION_COLUMNS = (
    "event_class",
    "event_description",
    "event_basename",
    "event_flags",
    "title_en",
    "title_he",
    "title_ashkenazi",
)
SCHEDULE_KEYS = {"diaspora": 0, "israel": 1}
OFFICIAL_CORPUS_MANIFEST_SHA256 = (
    "021fb23d9f30f614141a102691e9453c83717ae7963dff18a83aba0d78a46450"
)
OFFICIAL_EVENT_DEFINITION_FINGERPRINT = (
    "108ea0bfffe3e5fe214a1fe3e6dc4bf4cb9e85d36f230adb2f42453b5a5b47b6"
)
OFFICIAL_VALIDATION = {
    "hebrew_day_schedule": {
        "rows": 4_382_930,
        "rows_by_schedule": {"diaspora": 2_191_465, "israel": 2_191_465},
        "unsupported_tachanun_rows": 710,
    },
    "hebcal_event_definition": {
        "rows": 142_603,
        "event_definition_fingerprint_sha256": (
            OFFICIAL_EVENT_DEFINITION_FINGERPRINT
        ),
    },
    "hebcal_event_occurrence": {
        "rows": 2_037_895,
        "rows_by_schedule": {"diaspora": 1_027_106, "israel": 1_010_789},
    },
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
    text = str(value)
    return "'" + text.replace("\\", "/").replace("'", "''") + "'"


def sql_path_list(paths: list[Path]) -> str:
    return "[" + ", ".join(sql_literal(path.resolve()) for path in paths) + "]"


def scalar(connection: duckdb.DuckDBPyConnection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def _verify_source_manifest(
    corpus_root: Path,
) -> tuple[dict[str, Any], str, dict[str, list[Path]]]:
    manifest_path = corpus_root / "manifest.json"
    provenance_path = corpus_root / "provenance.json"
    if not manifest_path.is_file() or not provenance_path.is_file():
        raise RuntimeError(
            f"{corpus_root} is not a finalized corpus: manifest/provenance missing"
        )

    manifest = load_json(manifest_path)
    manifest_hash = sha256(manifest_path)
    provenance = load_json(provenance_path)
    if manifest.get("status") != "complete-immutable":
        raise RuntimeError("source corpus status is not complete-immutable")
    if manifest.get("corpus_version") != "v1":
        raise RuntimeError("powerbi-v1 requires corpus-v1")
    if provenance.get("content_manifest_sha256") != manifest_hash:
        raise RuntimeError("source provenance does not match the corpus manifest")

    partitions = manifest.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        raise RuntimeError("source manifest contains no partitions")

    table_paths = {file_name: [] for file_name in SOURCE_TABLE_FILES}
    for partition in partitions:
        block = partition.get("block")
        files = partition.get("files")
        if not isinstance(block, str) or not isinstance(files, dict):
            raise RuntimeError("source manifest contains an invalid partition entry")

        partition_root = corpus_root / f"block={block}"
        partition_manifest = partition_root / "manifest.json"
        expected_partition_hash = partition.get("manifest_sha256")
        if expected_partition_hash:
            if not partition_manifest.is_file():
                raise RuntimeError(f"{partition_manifest} is missing")
            if sha256(partition_manifest) != expected_partition_hash:
                raise RuntimeError(
                    f"{partition_manifest} checksum does not match the root manifest"
                )

        for file_name in SOURCE_TABLE_FILES:
            file_entry = files.get(file_name)
            if not isinstance(file_entry, dict) or "sha256" not in file_entry:
                raise RuntimeError(f"{block} does not manifest {file_name}")
            path = partition_root / file_name
            if not path.is_file():
                raise RuntimeError(f"{path} is missing")
            if sha256(path) != file_entry["sha256"]:
                raise RuntimeError(f"{path} checksum does not match the root manifest")
            table_paths[file_name].append(path)

    return manifest, manifest_hash, table_paths


def _create_source_views(
    connection: duckdb.DuckDBPyConnection,
    table_paths: dict[str, list[Path]],
) -> None:
    connection.execute(
        f"""
        CREATE TEMP VIEW source_day AS
        SELECT *
        FROM read_parquet(
            {sql_path_list(table_paths["core_day.parquet"])},
            union_by_name = true,
            hive_partitioning = false
        )
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW source_day_schedule AS
        SELECT *
        FROM read_parquet(
            {sql_path_list(table_paths["core_day_schedule.parquet"])},
            union_by_name = true,
            hive_partitioning = false
        )
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW source_event_occurrence AS
        SELECT *
        FROM read_parquet(
            {sql_path_list(table_paths["core_event_occurrence.parquet"])},
            union_by_name = true,
            hive_partitioning = false
        )
        """
    )


def _rows_by_source_schedule(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> dict[str, int]:
    return {
        str(schedule): int(rows)
        for schedule, rows in connection.execute(
            f"""
            SELECT schedule, count(*)
            FROM {table_name}
            GROUP BY schedule
            ORDER BY schedule
            """
        ).fetchall()
    }


def _rows_by_schedule_key(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> dict[str, int]:
    schedule_names = {value: key for key, value in SCHEDULE_KEYS.items()}
    return {
        schedule_names[int(schedule_key)]: int(rows)
        for schedule_key, rows in connection.execute(
            f"""
            SELECT schedule_key, count(*)
            FROM {table_name}
            GROUP BY schedule_key
            ORDER BY schedule_key
            """
        ).fetchall()
    }


def _validate_source(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    day_rows, unique_days = connection.execute(
        "SELECT count(*), count(DISTINCT absolute_day) FROM source_day"
    ).fetchone()
    if not day_rows or day_rows != unique_days:
        raise RuntimeError(
            f"source day key mismatch: rows={day_rows}, unique={unique_days}"
        )

    schedules = {
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT schedule
            FROM (
                SELECT schedule FROM source_day_schedule
                UNION ALL
                SELECT schedule FROM source_event_occurrence
            )
            """
        ).fetchall()
    }
    if not schedules.issubset(SCHEDULE_KEYS) or not set(SCHEDULE_KEYS).issubset(
        {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT schedule FROM source_day_schedule"
            ).fetchall()
        }
    ):
        raise RuntimeError(f"unexpected source schedules: {sorted(schedules)}")

    schedule_rows, schedule_keys = connection.execute(
        """
        SELECT count(*), count(DISTINCT (absolute_day, schedule))
        FROM source_day_schedule
        """
    ).fetchone()
    if schedule_rows != day_rows * 2 or schedule_keys != schedule_rows:
        raise RuntimeError(
            "source day schedule must contain one row per day and schedule"
        )

    schedule_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_day_schedule AS schedule
        ANTI JOIN source_day AS day USING (absolute_day)
        """,
    )
    event_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_event_occurrence AS event
        ANTI JOIN source_day AS day USING (absolute_day)
        """,
    )
    if schedule_orphans or event_orphans:
        raise RuntimeError(
            "source rows outside the day spine: "
            f"schedule={schedule_orphans}, event={event_orphans}"
        )

    invalid_hallel = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_day_schedule
        WHERE hallel IS NULL OR hallel NOT BETWEEN 0 AND 2
        """,
    )
    invalid_tachanun = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_day_schedule
        WHERE tachanun_supported IS NULL
           OR (
                tachanun_json IS NOT NULL
                AND NOT json_valid(tachanun_json)
           )
           OR (tachanun_supported AND tachanun_json IS NULL)
           OR (NOT tachanun_supported AND tachanun_json IS NOT NULL)
        """,
    )
    invalid_eruv = scalar(
        connection,
        "SELECT count(*) FROM source_day_schedule WHERE eruv_tavshilin IS NULL",
    )
    if invalid_hallel or invalid_tachanun or invalid_eruv:
        raise RuntimeError(
            "invalid source schedule values: "
            f"hallel={invalid_hallel}, tachanun={invalid_tachanun}, "
            f"eruv={invalid_eruv}"
        )

    tuple_null_predicate = " OR ".join(
        f"{column} IS NULL" for column in EVENT_DEFINITION_COLUMNS
    )
    null_event_definitions = scalar(
        connection,
        f"""
        SELECT count(*)
        FROM source_event_occurrence
        WHERE absolute_day IS NULL
           OR schedule IS NULL
           OR {tuple_null_predicate}
        """,
    )
    if null_event_definitions:
        raise RuntimeError(
            f"source event occurrences contain {null_event_definitions} null keys"
        )

    return {
        "core_day_rows": day_rows,
        "core_day_schedule_rows": schedule_rows,
        "core_day_schedule_rows_by_schedule": _rows_by_source_schedule(
            connection, "source_day_schedule"
        ),
        "core_event_occurrence_rows": scalar(
            connection, "SELECT count(*) FROM source_event_occurrence"
        ),
        "core_event_occurrence_rows_by_schedule": _rows_by_source_schedule(
            connection, "source_event_occurrence"
        ),
    }


def _create_derived_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE hebrew_day_schedule AS
        SELECT
            CAST(absolute_day AS INTEGER) AS absolute_day,
            CAST(
                CASE schedule
                    WHEN 'diaspora' THEN 0
                    WHEN 'israel' THEN 1
                END
                AS TINYINT
            ) AS schedule_key,
            CAST(hallel AS TINYINT) AS hallel_level,
            CAST(
                json_extract_string(tachanun_json, '$.shacharit')
                AS BOOLEAN
            ) AS tachanun_shacharit,
            CAST(
                json_extract_string(tachanun_json, '$.mincha')
                AS BOOLEAN
            ) AS tachanun_mincha,
            CAST(
                json_extract_string(tachanun_json, '$.allCongs')
                AS BOOLEAN
            ) AS tachanun_all_congregations,
            CAST(tachanun_supported AS BOOLEAN) AS tachanun_supported,
            CAST(eruv_tavshilin AS BOOLEAN) AS eruv_tavshilin
        FROM source_day_schedule
        """
    )

    order_columns = ", ".join(EVENT_DEFINITION_COLUMNS)
    order_expressions = ", ".join(
        (
            f"({column} IS NULL), {column}"
            if column == "event_flags"
            else f"({column} IS NULL), encode(coalesce({column}, ''))"
        )
        for column in EVENT_DEFINITION_COLUMNS
    )
    select_columns = ",\n                ".join(EVENT_DEFINITION_COLUMNS)
    connection.execute(
        f"""
        CREATE TEMP TABLE hebcal_event_definition AS
        SELECT
            CAST(
                row_number() OVER (ORDER BY {order_expressions})
                AS INTEGER
            ) AS event_definition_key,
            {select_columns}
        FROM (
            SELECT DISTINCT {order_columns}
            FROM source_event_occurrence
        ) AS definitions
        """
    )

    join_predicate = "\n           AND ".join(
        f"event.{column} IS NOT DISTINCT FROM definition.{column}"
        for column in EVENT_DEFINITION_COLUMNS
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE hebcal_event_occurrence AS
        SELECT
            CAST(event.absolute_day AS INTEGER) AS absolute_day,
            CAST(
                CASE event.schedule
                    WHEN 'diaspora' THEN 0
                    WHEN 'israel' THEN 1
                END
                AS TINYINT
            ) AS schedule_key,
            CAST(definition.event_definition_key AS INTEGER)
                AS event_definition_key
        FROM source_event_occurrence AS event
        JOIN hebcal_event_definition AS definition
          ON {join_predicate}
        """
    )


def _copy_derived_tables(
    connection: duckdb.DuckDBPyConnection, artifact_root: Path
) -> None:
    exports = {
        "hebrew_day_schedule": "absolute_day, schedule_key",
        "hebcal_event_definition": "event_definition_key",
        "hebcal_event_occurrence": (
            "absolute_day, schedule_key, event_definition_key"
        ),
    }
    for table_name, order_by in exports.items():
        connection.execute(
            f"""
            COPY (
                SELECT *
                FROM {table_name}
                ORDER BY {order_by}
            )
            TO {sql_literal(artifact_root / f"{table_name}.parquet")}
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                ROW_GROUP_SIZE 100000
            )
            """
        )


def _create_output_views(
    connection: duckdb.DuckDBPyConnection, artifact_root: Path
) -> None:
    for file_name in OUTPUT_TABLE_FILES:
        table_name = Path(file_name).stem
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW output_{table_name} AS
            SELECT *
            FROM read_parquet(
                {sql_literal(artifact_root / file_name)},
                hive_partitioning = false
            )
            """
        )


def _validate_outputs(
    connection: duckdb.DuckDBPyConnection,
    source_counts: dict[str, Any],
) -> dict[str, Any]:
    schedule_rows, schedule_keys = connection.execute(
        """
        SELECT count(*), count(DISTINCT (absolute_day, schedule_key))
        FROM output_hebrew_day_schedule
        """
    ).fetchone()
    if (
        schedule_rows != source_counts["core_day_schedule_rows"]
        or schedule_rows != schedule_keys
    ):
        raise RuntimeError(
            f"derived schedule key mismatch: rows={schedule_rows}, "
            f"unique={schedule_keys}, "
            f"source={source_counts['core_day_schedule_rows']}"
        )

    schedule_nulls = connection.execute(
        """
        SELECT
            count(*) FILTER (WHERE absolute_day IS NULL),
            count(*) FILTER (WHERE schedule_key IS NULL),
            count(*) FILTER (WHERE hallel_level IS NULL),
            count(*) FILTER (WHERE tachanun_shacharit IS NULL),
            count(*) FILTER (WHERE tachanun_mincha IS NULL),
            count(*) FILTER (WHERE tachanun_all_congregations IS NULL),
            count(*) FILTER (WHERE tachanun_supported IS NULL),
            count(*) FILTER (WHERE eruv_tavshilin IS NULL),
            count(*) FILTER (WHERE NOT tachanun_supported)
        FROM output_hebrew_day_schedule
        """
    ).fetchone()
    unsupported_rows = schedule_nulls[8]
    if (
        schedule_nulls[:3] != (0, 0, 0)
        or schedule_nulls[3:6]
        != (unsupported_rows, unsupported_rows, unsupported_rows)
        or schedule_nulls[6:8] != (0, 0)
    ):
        raise RuntimeError(
            "derived schedule null contract failed: "
            f"null_counts={schedule_nulls[:8]}, unsupported={unsupported_rows}"
        )
    invalid_tachanun_nulls = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebrew_day_schedule
        WHERE (
            tachanun_supported
            AND (
                tachanun_shacharit IS NULL
                OR tachanun_mincha IS NULL
                OR tachanun_all_congregations IS NULL
            )
        )
        OR (
            NOT tachanun_supported
            AND (
                tachanun_shacharit IS NOT NULL
                OR tachanun_mincha IS NOT NULL
                OR tachanun_all_congregations IS NOT NULL
            )
        )
        """,
    )
    invalid_schedule_values = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebrew_day_schedule
        WHERE schedule_key NOT IN (0, 1)
           OR hallel_level NOT BETWEEN 0 AND 2
        """,
    )
    schedule_day_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebrew_day_schedule AS schedule
        ANTI JOIN source_day AS day USING (absolute_day)
        """,
    )
    if invalid_tachanun_nulls or invalid_schedule_values or schedule_day_orphans:
        raise RuntimeError(
            "derived schedule validation failed: "
            f"tachanun={invalid_tachanun_nulls}, "
            f"values={invalid_schedule_values}, "
            f"day_orphans={schedule_day_orphans}"
        )
    schedule_rows_by_schedule = _rows_by_schedule_key(
        connection, "output_hebrew_day_schedule"
    )
    if (
        schedule_rows_by_schedule
        != source_counts["core_day_schedule_rows_by_schedule"]
    ):
        raise RuntimeError(
            "derived day-schedule split does not match source: "
            f"derived={schedule_rows_by_schedule}, "
            f"source={source_counts['core_day_schedule_rows_by_schedule']}"
        )

    definition_rows, definition_keys, minimum_key, maximum_key = (
        connection.execute(
            """
            SELECT
                count(*),
                count(DISTINCT event_definition_key),
                min(event_definition_key),
                max(event_definition_key)
            FROM output_hebcal_event_definition
            """
        ).fetchone()
    )
    distinct_tuple = scalar(
        connection,
        f"""
        SELECT count(DISTINCT ({", ".join(EVENT_DEFINITION_COLUMNS)}))
        FROM output_hebcal_event_definition
        """,
    )
    definition_nulls = scalar(
        connection,
        f"""
        SELECT count(*)
        FROM output_hebcal_event_definition
        WHERE event_definition_key IS NULL
           OR {" OR ".join(f"{column} IS NULL" for column in EVENT_DEFINITION_COLUMNS)}
        """,
    )
    if (
        definition_rows != definition_keys
        or definition_rows != distinct_tuple
        or definition_nulls
        or (definition_rows and (minimum_key != 1 or maximum_key != definition_rows))
    ):
        raise RuntimeError(
            "event definition key contract failed: "
            f"rows={definition_rows}, keys={definition_keys}, "
            f"tuples={distinct_tuple}, bounds={minimum_key}:{maximum_key}, "
            f"nulls={definition_nulls}"
        )
    event_definition_fingerprint = scalar(
        connection,
        """
        SELECT sha256(
            string_agg(
                to_json(struct_pack(
                    k := event_definition_key,
                    c := event_class,
                    d := event_description,
                    b := event_basename,
                    f := event_flags,
                    en := title_en,
                    he := title_he,
                    a := title_ashkenazi
                )),
                chr(10)
                ORDER BY event_definition_key
            )
        )
        FROM output_hebcal_event_definition
        """,
    )

    occurrence_rows, occurrence_keys = connection.execute(
        """
        SELECT
            count(*),
            count(
                DISTINCT (
                    absolute_day,
                    schedule_key,
                    event_definition_key
                )
            )
        FROM output_hebcal_event_occurrence
        """
    ).fetchone()
    occurrence_nulls = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebcal_event_occurrence
        WHERE absolute_day IS NULL
           OR schedule_key IS NULL
           OR event_definition_key IS NULL
        """,
    )
    occurrence_definition_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebcal_event_occurrence AS occurrence
        ANTI JOIN output_hebcal_event_definition AS definition
          USING (event_definition_key)
        """,
    )
    occurrence_day_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_hebcal_event_occurrence AS occurrence
        ANTI JOIN source_day AS day USING (absolute_day)
        """,
    )
    if (
        occurrence_rows != source_counts["core_event_occurrence_rows"]
        or occurrence_rows != occurrence_keys
        or occurrence_nulls
        or occurrence_definition_orphans
        or occurrence_day_orphans
    ):
        raise RuntimeError(
            "event occurrence key contract failed: "
            f"rows={occurrence_rows}, source="
            f"{source_counts['core_event_occurrence_rows']}, "
            f"unique={occurrence_keys}, nulls={occurrence_nulls}, "
            f"definition_orphans={occurrence_definition_orphans}, "
            f"day_orphans={occurrence_day_orphans}"
        )
    occurrence_rows_by_schedule = _rows_by_schedule_key(
        connection, "output_hebcal_event_occurrence"
    )
    if (
        occurrence_rows_by_schedule
        != source_counts["core_event_occurrence_rows_by_schedule"]
    ):
        raise RuntimeError(
            "derived event-occurrence split does not match source: "
            f"derived={occurrence_rows_by_schedule}, "
            f"source={source_counts['core_event_occurrence_rows_by_schedule']}"
        )

    return {
        "hebrew_day_schedule": {
            "rows": schedule_rows,
            "unique_keys": schedule_keys,
            "rows_by_schedule": schedule_rows_by_schedule,
            "unsupported_tachanun_rows": unsupported_rows,
            "day_orphans": schedule_day_orphans,
        },
        "hebcal_event_definition": {
            "rows": definition_rows,
            "unique_keys": definition_keys,
            "first_key": minimum_key,
            "last_key": maximum_key,
            "distinct_definition_tuples": distinct_tuple,
            "event_definition_fingerprint_sha256": (
                event_definition_fingerprint
            ),
        },
        "hebcal_event_occurrence": {
            "rows": occurrence_rows,
            "unique_keys": occurrence_keys,
            "rows_by_schedule": occurrence_rows_by_schedule,
            "definition_orphans": occurrence_definition_orphans,
            "day_orphans": occurrence_day_orphans,
        },
    }


def _validate_official_materialization(
    source_manifest_hash: str, validation: dict[str, Any]
) -> bool:
    if source_manifest_hash != OFFICIAL_CORPUS_MANIFEST_SHA256:
        return False
    for table_name, expected_values in OFFICIAL_VALIDATION.items():
        actual_values = validation[table_name]
        for key, expected in expected_values.items():
            actual = actual_values.get(key)
            if actual != expected:
                raise RuntimeError(
                    f"official {table_name}.{key} mismatch: "
                    f"expected={expected}, actual={actual}"
                )
    return True


def _parquet_columns(path: Path) -> list[dict[str, str]]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_literal(path)})"
        ).fetchall()
    return [
        {"name": row[0], "type": row[1], "nullable": row[2]}
        for row in rows
    ]


def materialize(corpus_root: Path, output_root: Path) -> Path:
    corpus_root = corpus_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(
            f"{output_root} already exists; {MATERIALIZATION_VERSION} cannot be rewritten"
        )
    if output_root == corpus_root or corpus_root in output_root.parents:
        raise ValueError("the Power BI materialization cannot be written inside corpus-v1")

    source_manifest, source_manifest_hash, table_paths = _verify_source_manifest(
        corpus_root
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
        with duckdb.connect() as connection:
            connection.execute("SET threads = 1")
            connection.execute("SET default_collation = ''")
            connection.execute("SET preserve_insertion_order = true")
            connection.execute(
                f"SET temp_directory = {sql_literal(duckdb_temp)}"
            )
            _create_source_views(connection, table_paths)
            source_counts = _validate_source(connection)
            _create_derived_tables(connection)
            _copy_derived_tables(connection, artifact_root)
            _create_output_views(connection, artifact_root)
            validation = _validate_outputs(connection, source_counts)
            official_baseline_verified = _validate_official_materialization(
                source_manifest_hash, validation
            )

        files: dict[str, Any] = {}
        for file_name in OUTPUT_TABLE_FILES:
            path = artifact_root / file_name
            files[file_name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "rows": validation[Path(file_name).stem]["rows"],
                "columns": _parquet_columns(path),
            }

        manifest = {
            "materialization_version": MATERIALIZATION_VERSION,
            "status": "complete-immutable-derived",
            "source": {
                "corpus_version": source_manifest["corpus_version"],
                "corpus_manifest_sha256": source_manifest_hash,
                "verified_partition_count": len(source_manifest["partitions"]),
                "verified_file_count": sum(
                    len(paths) for paths in table_paths.values()
                ),
            },
            "builder": {
                "script_sha256": sha256(Path(__file__).resolve()),
                "duckdb_version": duckdb.__version__,
            },
            "keys": {
                "schedule_key": SCHEDULE_KEYS,
                "event_definition_key": {
                    "base": 1,
                    "dense": True,
                    "sort_columns": list(EVENT_DEFINITION_COLUMNS),
                },
            },
            "files": files,
            "validation": validation,
            "official_corpus_v1_baseline_verified": official_baseline_verified,
            "immutability": {
                "overwrite_existing_output": False,
                "source_corpus_modified": False,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=DEFAULT_CORPUS_ROOT,
        help=f"finalized immutable source (default: {DEFAULT_CORPUS_ROOT})",
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
    print(materialize(args.corpus_root, args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
