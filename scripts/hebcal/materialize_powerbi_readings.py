#!/usr/bin/env python3
"""Materialize the immutable corpus-v1 Power BI readings boundary once.

The source corpus is opened read-only. The destination must not exist, and this
command deliberately has no overwrite or force option. Changed normalization
rules require a new materialization version rather than a rewrite of
powerbi-readings-v1.
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
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "hebcal" / "powerbi-readings-v1"

MATERIALIZATION_VERSION = "powerbi-readings-v1"
SOURCE_TABLE_FILES = (
    "core_day.parquet",
    "core_day_schedule.parquet",
    "core_parasha_occurrence.parquet",
    "core_leyning_occurrence.parquet",
)
OUTPUT_TABLE_FILES = (
    "parasha_definition.parquet",
    "parasha_definition_member.parquet",
    "parasha_occurrence.parquet",
    "leyning_reading_definition.parquet",
    "leyning_definition_parasha.parquet",
    "leyning_segment_definition.parquet",
    "leyning_occurrence.parquet",
)
SCHEDULE_KEYS = {"diaspora": 0, "israel": 1}

OFFICIAL_CORPUS_MANIFEST_SHA256 = (
    "021fb23d9f30f614141a102691e9453c83717ae7963dff18a83aba0d78a46450"
)

# Filled from the deterministic normalized tables. These values are not
# Parquet-byte hashes; provenance and file hashes are recorded separately.
OFFICIAL_FINGERPRINTS = {
    "parasha_definition": (
        "88a2aaedb0d1ce960bb24761b9d1a3ed809494e58011f37f80000d5c797f7332"
    ),
    "parasha_definition_member": (
        "9daf028f3f0231d301f71c04ba852a5fde1800ccb093288ceff36da63119ac9a"
    ),
    "leyning_reading_definition": (
        "2d967b7a5d4bbc8be7e5220258e6f389d03c6071f25caf93e1130e6dde260209"
    ),
    "leyning_definition_parasha": (
        "22c28511f9f8efcb782670dfbeff28ecfcbdc71b627c075e864d8fd97037d357"
    ),
    "leyning_segment_definition": (
        "97e291fbeb67223105c3b50bd71164ac41a8f4f1f77da57a27706cfb9a7322e5"
    ),
}

OFFICIAL_VALIDATION = {
    "parasha_definition": {
        "rows": 60,
        "unique_keys": 60,
        "combined_rows": 7,
        "single_rows": 53,
    },
    "parasha_definition_member": {
        "rows": 67,
        "unique_keys": 67,
        "rows_by_member_index": {"1": 60, "2": 7},
    },
    "parasha_occurrence": {
        "rows": 588_052,
        "unique_keys": 588_052,
        "rows_by_schedule": {"diaspora": 292_328, "israel": 295_724},
        "used_definition_count": 60,
        "day_orphans": 0,
        "schedule_orphans": 0,
        "definition_orphans": 0,
    },
    "leyning_reading_definition": {
        "rows": 269,
        "unique_keys": 269,
        "unique_payload_hashes": 269,
        "rows_by_type": {"holiday": 85, "shabbat": 123, "weekday": 61},
        "null_summaries": {
            "summary": 1,
            "summary_he": 1,
            "summary_ashkenazi": 1,
        },
    },
    "leyning_definition_parasha": {
        "rows": 202,
        "unique_keys": 202,
        "rows_by_member_index": {"1": 184, "2": 18},
        "represented_definition_count": 184,
        "first_parasha_number": 1,
        "last_parasha_number": 54,
    },
    "leyning_segment_definition": {
        "rows": 2_265,
        "unique_keys": 2_265,
        "rows_by_kind": {
            "alt": 24,
            "chabad": 18,
            "fullkriyah": 1_387,
            "haft": 182,
            "megillah": 168,
            "seph": 59,
            "summaryParts": 244,
            "weekday": 183,
        },
        "max_index_by_kind": {
            "alt": 6,
            "chabad": 2,
            "fullkriyah": 9,
            "haft": 3,
            "megillah": 12,
            "seph": 4,
            "summaryParts": 4,
            "weekday": 3,
        },
        "null_verse_count_rows": 244,
        "null_parasha_number_rows": 1_792,
        "populated_reason_rows": 190,
        "populated_note_rows": 1,
        "definition_orphans": 0,
        "non_dense_index_groups": 0,
    },
    "leyning_occurrence": {
        "rows": 2_339_622,
        "unique_keys": 2_339_622,
        "rows_by_schedule": {"diaspora": 1_172_415, "israel": 1_167_207},
        "rows_by_reading_index": {
            "0": 2_234_361,
            "1": 97_091,
            "2": 8_170,
        },
        "used_definition_count": 269,
        "day_orphans": 0,
        "schedule_orphans": 0,
        "definition_orphans": 0,
    },
}

READING_DEFINITION_SOURCE_COLUMNS = (
    "source_payload_sha256",
    "reading_type",
    "name_en",
    "name_he",
    "summary",
    "summary_he",
    "summary_ashkenazi",
    "parasha_json",
    "parasha_num_json",
    "raw_reading_json",
    "raw_reading_json_he",
    "raw_reading_json_ashkenazi",
)

JSON_ROOT_KEYS = frozenset(
    {
        "alt",
        "chabad",
        "fullkriyah",
        "haft",
        "haftara",
        "haftaraNumV",
        "megillah",
        "name",
        "note",
        "parsha",
        "parshaNum",
        "reason",
        "seph",
        "sephardic",
        "sephardicNumV",
        "summary",
        "summaryParts",
        "type",
        "weekday",
    }
)
REQUIRED_JSON_ROOT_KEYS = frozenset({"name", "type"})
REASON_KEYS = frozenset(
    {"1", "2", "3", "4", "7", "M", "chabad", "haftara", "sephardic"}
)
KEYED_PASSAGE_LABELS = {
    "fullkriyah": frozenset({str(value) for value in range(1, 9)} | {"M"}),
    "weekday": frozenset({"1", "2", "3"}),
    "alt": frozenset({str(value) for value in range(1, 6)} | {"M"}),
    "megillah": frozenset({str(value) for value in range(1, 13)}),
}
PASSAGE_FIELD_RULES = {
    "fullkriyah": (
        frozenset({"b", "e", "k", "v"}),
        frozenset({"p", "reason"}),
    ),
    "weekday": (frozenset({"b", "e", "k", "v"}), frozenset()),
    "alt": (frozenset({"b", "e", "k", "v", "p"}), frozenset()),
    "haft": (
        frozenset({"b", "e", "k", "v"}),
        frozenset({"reason", "note"}),
    ),
    "seph": (
        frozenset({"b", "e", "k", "v"}),
        frozenset({"reason"}),
    ),
    "chabad": (
        frozenset({"b", "e", "k", "v"}),
        frozenset({"reason"}),
    ),
    "megillah": (frozenset({"b", "e", "k", "v"}), frozenset()),
    "summaryParts": (frozenset({"b", "e", "k"}), frozenset()),
}
SEGMENT_KINDS = frozenset(PASSAGE_FIELD_RULES)


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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        raise RuntimeError(f"{MATERIALIZATION_VERSION} requires corpus-v1")
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
        if (
            not isinstance(expected_partition_hash, str)
            or len(expected_partition_hash) != 64
        ):
            raise RuntimeError(
                f"{block} has no valid partition manifest checksum"
            )
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
    view_names = {
        "core_day.parquet": "source_day",
        "core_day_schedule.parquet": "source_day_schedule",
        "core_parasha_occurrence.parquet": "source_parasha_occurrence",
        "core_leyning_occurrence.parquet": "source_leyning_occurrence",
    }
    for file_name, view_name in view_names.items():
        connection.execute(
            f"""
            CREATE TEMP VIEW {view_name} AS
            SELECT *
            FROM read_parquet(
                {sql_path_list(table_paths[file_name])},
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
        value
        for (value,) in connection.execute(
            """
            SELECT DISTINCT schedule
            FROM (
                SELECT schedule FROM source_day_schedule
                UNION ALL
                SELECT schedule FROM source_parasha_occurrence
                UNION ALL
                SELECT schedule FROM source_leyning_occurrence
            )
            """
        ).fetchall()
    }
    if schedules != set(SCHEDULE_KEYS):
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

    parasha_rows, parasha_ids, parasha_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT occurrence_id),
            count(DISTINCT (absolute_day, schedule))
        FROM source_parasha_occurrence
        """
    ).fetchone()
    leyning_rows, leyning_ids, leyning_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT occurrence_id),
            count(DISTINCT (absolute_day, schedule, reading_index))
        FROM source_leyning_occurrence
        """
    ).fetchone()
    if parasha_rows != parasha_ids or parasha_rows != parasha_keys:
        raise RuntimeError(
            "source parasha occurrence IDs or natural keys are not unique"
        )
    if leyning_rows != leyning_ids or leyning_rows != leyning_keys:
        raise RuntimeError(
            "source leyning occurrence IDs or natural keys are not unique"
        )

    invalid_parasha = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_parasha_occurrence
        WHERE occurrence_id IS NULL
           OR hebrew_year IS NULL
           OR schedule IS NULL
           OR absolute_day IS NULL
           OR parasha IS NULL
           OR len(parasha) NOT BETWEEN 1 AND 2
           OR is_combined IS NULL
           OR is_combined <> (len(parasha) = 2)
           OR title_en IS NULL
           OR title_he IS NULL
           OR title_ashkenazi IS NULL
           OR basename IS NULL
           OR raw_event_json IS NULL
           OR NOT json_valid(raw_event_json)
        """,
    )
    invalid_leyning = scalar(
        connection,
        """
        SELECT count(*)
        FROM source_leyning_occurrence
        WHERE occurrence_id IS NULL
           OR hebrew_year IS NULL
           OR schedule IS NULL
           OR absolute_day IS NULL
           OR reading_index IS NULL
           OR reading_index NOT BETWEEN 0 AND 2
           OR reading_type IS NULL
           OR name_en IS NULL
           OR name_he IS NULL
           OR (parasha_json IS NULL) <> (parasha_num_json IS NULL)
           OR (parasha_json IS NOT NULL AND NOT json_valid(parasha_json))
           OR (
                parasha_num_json IS NOT NULL
                AND NOT json_valid(parasha_num_json)
           )
           OR raw_reading_json IS NULL
           OR NOT json_valid(raw_reading_json)
           OR raw_reading_json_he IS NULL
           OR NOT json_valid(raw_reading_json_he)
           OR raw_reading_json_ashkenazi IS NULL
           OR NOT json_valid(raw_reading_json_ashkenazi)
           OR source_payload_sha256 IS NULL
           OR NOT regexp_full_match(source_payload_sha256, '[0-9a-f]{64}')
        """,
    )
    if invalid_parasha or invalid_leyning:
        raise RuntimeError(
            "invalid source reading rows: "
            f"parasha={invalid_parasha}, leyning={invalid_leyning}"
        )

    noncontiguous_indexes = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT
                absolute_day,
                schedule,
                min(reading_index) AS first_index,
                max(reading_index) AS last_index,
                count(*) AS rows,
                count(DISTINCT reading_index) AS distinct_indexes
            FROM source_leyning_occurrence
            GROUP BY absolute_day, schedule
            HAVING first_index <> 0
                OR last_index <> rows - 1
                OR distinct_indexes <> rows
        )
        """,
    )
    if noncontiguous_indexes:
        raise RuntimeError(
            f"source leyning has {noncontiguous_indexes} index gaps"
        )

    integrity = connection.execute(
        """
        SELECT
            (
                SELECT count(*)
                FROM source_parasha_occurrence AS occurrence
                ANTI JOIN source_day AS day USING (absolute_day)
            ),
            (
                SELECT count(*)
                FROM source_parasha_occurrence AS occurrence
                ANTI JOIN source_day_schedule AS schedule
                  USING (absolute_day, schedule)
            ),
            (
                SELECT count(*)
                FROM source_leyning_occurrence AS occurrence
                ANTI JOIN source_day AS day USING (absolute_day)
            ),
            (
                SELECT count(*)
                FROM source_leyning_occurrence AS occurrence
                ANTI JOIN source_day_schedule AS schedule
                  USING (absolute_day, schedule)
            ),
            (
                SELECT count(*)
                FROM source_parasha_occurrence AS occurrence
                JOIN source_day AS day USING (absolute_day)
                WHERE occurrence.hebrew_year <> day.hebrew_year
                   OR day.weekday_sunday_0 <> 6
            ),
            (
                SELECT count(*)
                FROM source_leyning_occurrence AS occurrence
                JOIN source_day AS day USING (absolute_day)
                WHERE occurrence.hebrew_year <> day.hebrew_year
            )
        """
    ).fetchone()
    if any(integrity):
        raise RuntimeError(f"source reading relationship integrity failed: {integrity}")

    hash_variants = scalar(
        connection,
        f"""
        SELECT count(*)
        FROM (
            SELECT
                source_payload_sha256,
                count(DISTINCT ({", ".join(READING_DEFINITION_SOURCE_COLUMNS)}))
                    AS variants
            FROM source_leyning_occurrence
            GROUP BY source_payload_sha256
            HAVING variants <> 1
        )
        """,
    )
    if hash_variants:
        raise RuntimeError(
            f"{hash_variants} leyning hashes map to multiple payload definitions"
        )

    return {
        "core_day_rows": int(day_rows),
        "core_day_schedule_rows": int(schedule_rows),
        "core_parasha_occurrence_rows": int(parasha_rows),
        "core_parasha_occurrence_rows_by_schedule": _rows_by_source_schedule(
            connection, "source_parasha_occurrence"
        ),
        "core_leyning_occurrence_rows": int(leyning_rows),
        "core_leyning_occurrence_rows_by_schedule": _rows_by_source_schedule(
            connection, "source_leyning_occurrence"
        ),
    }


def _expect_type(
    value: Any, expected: type | tuple[type, ...], path: str
) -> None:
    if not isinstance(value, expected) or (
        expected is int and isinstance(value, bool)
    ):
        raise RuntimeError(
            f"unexpected JSON type at {path}: {type(value).__name__}"
        )


def _structure_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return (
            "object",
            tuple(
                (key, _structure_signature(child))
                for key, child in sorted(value.items())
            ),
        )
    if isinstance(value, list):
        return ("array", tuple(_structure_signature(child) for child in value))
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _validate_passage_entry(entry: Any, root_key: str, path: str) -> None:
    _expect_type(entry, dict, path)
    required, optional = PASSAGE_FIELD_RULES[root_key]
    keys = set(entry)
    missing = required - keys
    unknown = keys - required - optional
    if missing or unknown:
        raise RuntimeError(
            f"unexpected passage fields at {path}: "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    for key in ("b", "e", "k"):
        _expect_type(entry[key], str, f"{path}.{key}")
    for key in ("v", "p"):
        if key in entry:
            _expect_type(entry[key], int, f"{path}.{key}")
    for key in ("reason", "note"):
        if key in entry:
            _expect_type(entry[key], str, f"{path}.{key}")


def _validate_json_root(value: Any, locale: str, payload_hash: str) -> None:
    path = f"{payload_hash}.{locale}"
    _expect_type(value, dict, path)
    keys = set(value)
    unknown = keys - JSON_ROOT_KEYS
    missing = REQUIRED_JSON_ROOT_KEYS - keys
    if unknown or missing:
        raise RuntimeError(
            f"unexpected JSON root at {path}: "
            f"missing={sorted(missing)}, unknown={sorted(unknown)}"
        )

    name = value["name"]
    _expect_type(name, dict, f"{path}.name")
    if set(name) != {"en", "he"}:
        raise RuntimeError(f"unexpected name fields at {path}.name")
    _expect_type(name["en"], str, f"{path}.name.en")
    _expect_type(name["he"], str, f"{path}.name.he")
    _expect_type(value["type"], str, f"{path}.type")

    for key in ("summary", "haftara", "sephardic", "note"):
        if key in value:
            _expect_type(value[key], str, f"{path}.{key}")
    for key in ("haftaraNumV", "sephardicNumV"):
        if key in value:
            _expect_type(value[key], int, f"{path}.{key}")

    if "parsha" in value:
        _expect_type(value["parsha"], list, f"{path}.parsha")
        if not value["parsha"]:
            raise RuntimeError(f"empty parsha array at {path}.parsha")
        for index, item in enumerate(value["parsha"]):
            _expect_type(item, str, f"{path}.parsha[{index}]")
        if "parshaNum" not in value:
            raise RuntimeError(f"parshaNum missing at {path}")
        numbers = value["parshaNum"]
        if isinstance(numbers, list):
            if len(numbers) != len(value["parsha"]):
                raise RuntimeError(f"parsha/parshaNum length mismatch at {path}")
            for index, item in enumerate(numbers):
                _expect_type(item, int, f"{path}.parshaNum[{index}]")
        else:
            _expect_type(numbers, int, f"{path}.parshaNum")
            if len(value["parsha"]) != 1:
                raise RuntimeError(f"scalar parshaNum with combined parsha at {path}")
    elif "parshaNum" in value:
        raise RuntimeError(f"parshaNum without parsha at {path}")

    if "reason" in value:
        reasons = value["reason"]
        _expect_type(reasons, dict, f"{path}.reason")
        unknown_reasons = set(reasons) - REASON_KEYS
        if unknown_reasons:
            raise RuntimeError(
                f"unknown reason keys at {path}: {sorted(unknown_reasons)}"
            )
        for key, reason in reasons.items():
            _expect_type(reason, str, f"{path}.reason.{key}")

    for root_key, labels in KEYED_PASSAGE_LABELS.items():
        if root_key not in value:
            continue
        container = value[root_key]
        _expect_type(container, dict, f"{path}.{root_key}")
        if not container:
            raise RuntimeError(f"empty {root_key} passage object at {path}")
        unknown_labels = set(container) - labels
        if unknown_labels:
            raise RuntimeError(
                f"unknown {root_key} labels at {path}: {sorted(unknown_labels)}"
            )
        for label, entry in container.items():
            _validate_passage_entry(
                entry, root_key, f"{path}.{root_key}.{label}"
            )

    for root_key in ("haft", "seph", "chabad"):
        if root_key not in value:
            continue
        container = value[root_key]
        entries = container if isinstance(container, list) else [container]
        if not entries:
            raise RuntimeError(f"empty {root_key} passage list at {path}")
        for index, entry in enumerate(entries, start=1):
            _validate_passage_entry(
                entry, root_key, f"{path}.{root_key}[{index}]"
            )

    if "summaryParts" in value:
        entries = value["summaryParts"]
        _expect_type(entries, list, f"{path}.summaryParts")
        if not entries:
            raise RuntimeError(f"empty summaryParts at {path}")
        for index, entry in enumerate(entries, start=1):
            _validate_passage_entry(
                entry, "summaryParts", f"{path}.summaryParts[{index}]"
            )


def _label_ordinal(label: str) -> int:
    if label == "M":
        return 99
    return int(label)


def _segment_entries(
    value: dict[str, Any],
) -> list[tuple[str, str, int, dict[str, Any], str | None]]:
    rows: list[tuple[str, str, int, dict[str, Any], str | None]] = []
    root_reasons = value.get("reason", {})
    for root_key in (
        "fullkriyah",
        "weekday",
        "alt",
        "haft",
        "seph",
        "chabad",
        "megillah",
        "summaryParts",
    ):
        if root_key not in value:
            continue
        segment_kind = root_key
        container = value[root_key]
        if root_key in KEYED_PASSAGE_LABELS:
            for segment_index, label in enumerate(
                sorted(container, key=_label_ordinal), start=1
            ):
                reason_key = label if root_key == "fullkriyah" else None
                rows.append(
                    (
                        segment_kind,
                        label,
                        segment_index,
                        container[label],
                        reason_key,
                    )
                )
        else:
            entries = container if isinstance(container, list) else [container]
            reason_key = {
                "haft": "haftara",
                "seph": "sephardic",
                "chabad": "chabad",
                "summaryParts": None,
            }[root_key]
            for segment_index, entry in enumerate(entries, start=1):
                rows.append(
                    (
                        segment_kind,
                        str(segment_index),
                        segment_index,
                        entry,
                        reason_key,
                    )
                )

    unmatched_reasons = dict(root_reasons)
    for _, _, _, entry, reason_key in rows:
        if reason_key is None or reason_key not in unmatched_reasons:
            continue
        if entry.get("reason") != unmatched_reasons[reason_key]:
            raise RuntimeError(
                f"top-level reason {reason_key} differs from passage reason"
            )
        unmatched_reasons.pop(reason_key)
    if unmatched_reasons:
        raise RuntimeError(
            f"top-level reasons have no passage: {sorted(unmatched_reasons)}"
        )
    return rows


def _parse_leyning_definitions(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[
    list[tuple[Any, ...]],
    list[tuple[Any, ...]],
    list[tuple[Any, ...]],
    dict[str, int],
]:
    select_columns = ", ".join(READING_DEFINITION_SOURCE_COLUMNS)
    rows = connection.execute(
        f"""
        SELECT DISTINCT {select_columns}
        FROM source_leyning_occurrence
        ORDER BY source_payload_sha256
        """
    ).fetchall()

    definitions: list[tuple[Any, ...]] = []
    parasha_members: list[tuple[Any, ...]] = []
    segments: list[tuple[Any, ...]] = []
    portion_numbers: dict[str, int] = {}
    number_names: dict[int, str] = {}

    for reading_definition_key, row in enumerate(rows, start=1):
        (
            payload_hash,
            reading_type,
            name_en,
            name_he,
            summary_en,
            summary_he,
            summary_ashkenazi,
            parasha_json,
            parasha_num_json,
            raw_en,
            raw_he,
            raw_ashkenazi,
        ) = row
        if sha256_text(raw_en) != payload_hash:
            raise RuntimeError(
                f"source payload hash does not match English JSON: {payload_hash}"
            )

        locale_values = {
            "en": json.loads(raw_en),
            "he": json.loads(raw_he),
            "ashkenazi": json.loads(raw_ashkenazi),
        }
        for locale, value in locale_values.items():
            _validate_json_root(value, locale, payload_hash)
        signatures = {
            _structure_signature(value) for value in locale_values.values()
        }
        if len(signatures) != 1:
            raise RuntimeError(
                f"locale JSON structures differ for {payload_hash}"
            )

        english = locale_values["en"]
        hebrew = locale_values["he"]
        ashkenazi = locale_values["ashkenazi"]
        if (
            english["type"] != reading_type
            or english["name"]["en"] != name_en
            or english["name"]["he"] != name_he
            or english.get("summary") != summary_en
            or hebrew.get("summary") != summary_he
            or ashkenazi.get("summary") != summary_ashkenazi
        ):
            raise RuntimeError(
                f"normalized source columns differ from JSON for {payload_hash}"
            )

        expected_parasha = english.get("parsha")
        expected_numbers = english.get("parshaNum")
        if (
            (json.loads(parasha_json) if parasha_json is not None else None)
            != expected_parasha
            or (
                json.loads(parasha_num_json)
                if parasha_num_json is not None
                else None
            )
            != expected_numbers
        ):
            raise RuntimeError(
                f"parasha source columns differ from JSON for {payload_hash}"
            )
        for locale_value in (hebrew, ashkenazi):
            if (
                locale_value.get("parsha") != expected_parasha
                or locale_value.get("parshaNum") != expected_numbers
            ):
                raise RuntimeError(
                    f"locale parasha structures differ for {payload_hash}"
                )

        for numeric_key in ("haftaraNumV", "sephardicNumV"):
            values = [value.get(numeric_key) for value in locale_values.values()]
            if len(set(values)) != 1:
                raise RuntimeError(
                    f"locale {numeric_key} values differ for {payload_hash}"
                )

        definitions.append(
            (
                reading_definition_key,
                payload_hash,
                reading_type,
                name_en,
                name_he,
                summary_en,
                summary_he,
                summary_ashkenazi,
            )
        )

        if expected_parasha is not None:
            numbers = (
                expected_numbers
                if isinstance(expected_numbers, list)
                else [expected_numbers]
            )
            for ordinal, (name, number) in enumerate(
                zip(expected_parasha, numbers, strict=True), start=1
            ):
                previous_number = portion_numbers.setdefault(name, number)
                previous_name = number_names.setdefault(number, name)
                if previous_number != number or previous_name != name:
                    raise RuntimeError(
                        f"parasha name/number mapping is not one-to-one: "
                        f"{name}={number}"
                    )
                parasha_members.append(
                    (reading_definition_key, ordinal, number, name)
                )

        locale_segments = {
            locale: _segment_entries(value)
            for locale, value in locale_values.items()
        }
        identities = {
            locale: [entry[:3] for entry in entries]
            for locale, entries in locale_segments.items()
        }
        if not (
            identities["en"]
            == identities["he"]
            == identities["ashkenazi"]
        ):
            raise RuntimeError(
                f"locale segment identities differ for {payload_hash}"
            )
        for entries in zip(
            locale_segments["en"],
            locale_segments["he"],
            locale_segments["ashkenazi"],
            strict=True,
        ):
            english_entry, hebrew_entry, ashkenazi_entry = entries
            segment_kind, label, segment_index = english_entry[:3]
            passage_values = [entry[3] for entry in entries]
            verse_counts = [value.get("v") for value in passage_values]
            parasha_numbers = [value.get("p") for value in passage_values]
            if len(set(verse_counts)) != 1 or len(set(parasha_numbers)) != 1:
                raise RuntimeError(
                    f"locale numeric segment values differ for {payload_hash}"
                )
            segments.append(
                (
                    reading_definition_key,
                    segment_kind,
                    label,
                    segment_index,
                    passage_values[0]["k"],
                    passage_values[1]["k"],
                    passage_values[2]["k"],
                    passage_values[0]["b"],
                    passage_values[1]["b"],
                    passage_values[2]["b"],
                    passage_values[0]["e"],
                    passage_values[1]["e"],
                    passage_values[2]["e"],
                    verse_counts[0],
                    parasha_numbers[0],
                    passage_values[0].get("reason"),
                    passage_values[1].get("reason"),
                    passage_values[2].get("reason"),
                    passage_values[0].get("note"),
                    passage_values[1].get("note"),
                    passage_values[2].get("note"),
                )
            )

    if len(portion_numbers) != len(number_names):
        raise RuntimeError("parasha name/number mapping is not bijective")
    return definitions, parasha_members, segments, portion_numbers


def _compact_json_utf8(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _create_derived_tables(connection: duckdb.DuckDBPyConnection) -> None:
    (
        leyning_definitions,
        leyning_parasha_members,
        leyning_segments,
        portion_numbers,
    ) = _parse_leyning_definitions(connection)

    connection.execute(
        """
        CREATE TEMP TABLE leyning_reading_definition (
            reading_definition_key INTEGER NOT NULL,
            source_payload_sha256 VARCHAR NOT NULL,
            reading_type VARCHAR NOT NULL,
            name_en VARCHAR NOT NULL,
            name_he VARCHAR NOT NULL,
            summary VARCHAR,
            summary_he VARCHAR,
            summary_ashkenazi VARCHAR
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO leyning_reading_definition
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        leyning_definitions,
    )

    connection.execute(
        """
        CREATE TEMP TABLE leyning_definition_parasha (
            reading_definition_key INTEGER NOT NULL,
            member_index TINYINT NOT NULL,
            parasha_name VARCHAR NOT NULL,
            parasha_number SMALLINT NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO leyning_definition_parasha VALUES (?, ?, ?, ?)",
        [
            (key, index, name, number)
            for key, index, number, name in leyning_parasha_members
        ],
    )

    connection.execute(
        """
        CREATE TEMP TABLE leyning_segment_definition (
            reading_definition_key INTEGER NOT NULL,
            segment_kind VARCHAR NOT NULL,
            segment_label VARCHAR NOT NULL,
            segment_index TINYINT NOT NULL,
            book_en VARCHAR NOT NULL,
            book_he VARCHAR NOT NULL,
            book_ashkenazi VARCHAR NOT NULL,
            begin_ref_en VARCHAR NOT NULL,
            begin_ref_he VARCHAR NOT NULL,
            begin_ref_ashkenazi VARCHAR NOT NULL,
            end_ref_en VARCHAR NOT NULL,
            end_ref_he VARCHAR NOT NULL,
            end_ref_ashkenazi VARCHAR NOT NULL,
            verse_count SMALLINT,
            parasha_number SMALLINT,
            reason_en VARCHAR,
            reason_he VARCHAR,
            reason_ashkenazi VARCHAR,
            note_en VARCHAR,
            note_he VARCHAR,
            note_ashkenazi VARCHAR
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO leyning_segment_definition
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        leyning_segments,
    )

    parasha_rows = connection.execute(
        """
        SELECT DISTINCT
            parasha,
            is_combined,
            title_en,
            title_he,
            title_ashkenazi,
            basename
        FROM source_parasha_occurrence
        """
    ).fetchall()
    parasha_rows.sort(
        key=lambda row: (
            _compact_json_utf8(row[0]),
            row[1],
            row[2].encode("utf-8"),
            row[3].encode("utf-8"),
            row[4].encode("utf-8"),
            row[5].encode("utf-8"),
        )
    )
    parasha_definitions: list[tuple[Any, ...]] = []
    parasha_definition_members: list[tuple[Any, ...]] = []
    parasha_maps: list[tuple[Any, ...]] = []
    for key, row in enumerate(parasha_rows, start=1):
        members, combined, title_en, title_he, title_ashkenazi, basename = row
        parasha_maps.append((key, members))
        parasha_definitions.append(
            (
                key,
                combined,
                title_en,
                title_he,
                title_ashkenazi,
                basename,
            )
        )
        for ordinal, name in enumerate(members, start=1):
            if name not in portion_numbers:
                raise RuntimeError(
                    f"parasha occurrence member has no canonical number: {name}"
                )
            parasha_definition_members.append((key, ordinal, name))

    connection.execute(
        """
        CREATE TEMP TABLE parasha_definition (
            parasha_definition_key INTEGER NOT NULL,
            is_combined BOOLEAN NOT NULL,
            title_en VARCHAR NOT NULL,
            title_he VARCHAR NOT NULL,
            title_ashkenazi VARCHAR NOT NULL,
            basename VARCHAR NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO parasha_definition VALUES (?, ?, ?, ?, ?, ?)",
        parasha_definitions,
    )
    connection.execute(
        """
        CREATE TEMP TABLE parasha_definition_member (
            parasha_definition_key INTEGER NOT NULL,
            member_index TINYINT NOT NULL,
            parasha_name VARCHAR NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO parasha_definition_member VALUES (?, ?, ?)",
        parasha_definition_members,
    )
    connection.execute(
        """
        CREATE TEMP TABLE parasha_definition_map (
            parasha_definition_key INTEGER NOT NULL,
            parasha VARCHAR[] NOT NULL
        )
        """
    )
    connection.executemany(
        "INSERT INTO parasha_definition_map VALUES (?, ?)",
        parasha_maps,
    )

    connection.execute(
        """
        CREATE TEMP TABLE parasha_occurrence AS
        SELECT
            CAST(occurrence.absolute_day AS INTEGER) AS absolute_day,
            CAST(
                CASE occurrence.schedule
                    WHEN 'diaspora' THEN 0
                    WHEN 'israel' THEN 1
                    ELSE error(
                        'Unexpected schedule: '
                        || coalesce(occurrence.schedule, '<null>')
                    )
                END
                AS TINYINT
            ) AS schedule_key,
            definition.parasha_definition_key
        FROM source_parasha_occurrence AS occurrence
        JOIN parasha_definition_map AS definition
          ON occurrence.parasha = definition.parasha
        """
    )

    connection.execute(
        """
        CREATE TEMP TABLE leyning_occurrence AS
        SELECT
            CAST(occurrence.absolute_day AS INTEGER) AS absolute_day,
            CAST(
                CASE occurrence.schedule
                    WHEN 'diaspora' THEN 0
                    WHEN 'israel' THEN 1
                    ELSE error(
                        'Unexpected schedule: '
                        || coalesce(occurrence.schedule, '<null>')
                    )
                END
                AS TINYINT
            ) AS schedule_key,
            CAST(occurrence.reading_index AS TINYINT) AS reading_index,
            definition.reading_definition_key
        FROM source_leyning_occurrence AS occurrence
        JOIN leyning_reading_definition AS definition
          USING (source_payload_sha256)
        """
    )


def _copy_derived_tables(
    connection: duckdb.DuckDBPyConnection, artifact_root: Path
) -> None:
    exports = {
        "parasha_definition": "parasha_definition_key",
        "parasha_definition_member": (
            "parasha_definition_key, member_index"
        ),
        "parasha_occurrence": (
            "absolute_day, schedule_key, parasha_definition_key"
        ),
        "leyning_reading_definition": "reading_definition_key",
        "leyning_definition_parasha": (
            "reading_definition_key, member_index"
        ),
        "leyning_segment_definition": (
            "reading_definition_key, segment_kind, segment_index"
        ),
        "leyning_occurrence": (
            "absolute_day, schedule_key, reading_index, "
            "reading_definition_key"
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


FINGERPRINT_EXPRESSIONS = {
    "parasha_definition": """
        to_json(struct_pack(
            k := parasha_definition_key,
            c := is_combined,
            en := title_en,
            he := title_he,
            a := title_ashkenazi,
            b := basename
        ))
    """,
    "parasha_definition_member": """
        to_json(struct_pack(
            k := parasha_definition_key,
            i := member_index,
            n := parasha_name
        ))
    """,
    "leyning_reading_definition": """
        to_json(struct_pack(
            k := reading_definition_key,
            h := source_payload_sha256,
            t := reading_type,
            en := name_en,
            he := name_he,
            s := summary,
            she := summary_he,
            sa := summary_ashkenazi
        ))
    """,
    "leyning_definition_parasha": """
        to_json(struct_pack(
            k := reading_definition_key,
            i := member_index,
            n := parasha_name,
            p := parasha_number
        ))
    """,
    "leyning_segment_definition": """
        to_json(struct_pack(
            k := reading_definition_key,
            g := segment_kind,
            l := segment_label,
            i := segment_index,
            ken := book_en,
            khe := book_he,
            ka := book_ashkenazi,
            ben := begin_ref_en,
            bhe := begin_ref_he,
            ba := begin_ref_ashkenazi,
            een := end_ref_en,
            ehe := end_ref_he,
            ea := end_ref_ashkenazi,
            v := verse_count,
            p := parasha_number,
            ren := reason_en,
            rhe := reason_he,
            ra := reason_ashkenazi,
            nen := note_en,
            nhe := note_he,
            na := note_ashkenazi
        ))
    """,
}

FINGERPRINT_ORDER = {
    "parasha_definition": "parasha_definition_key",
    "parasha_definition_member": "parasha_definition_key, member_index",
    "leyning_reading_definition": "reading_definition_key",
    "leyning_definition_parasha": "reading_definition_key, member_index",
    "leyning_segment_definition": (
        "reading_definition_key, segment_kind, segment_index"
    ),
}


def _fingerprint(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> str:
    return str(
        scalar(
            connection,
            f"""
            SELECT sha256(
                string_agg(
                    {FINGERPRINT_EXPRESSIONS[table_name]},
                    chr(10)
                    ORDER BY {FINGERPRINT_ORDER[table_name]}
                )
            )
            FROM output_{table_name}
            """,
        )
    )


def _dense_key_validation(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    key_name: str,
) -> tuple[int, int, int, int]:
    return tuple(
        int(value)
        for value in connection.execute(
            f"""
            SELECT
                count(*),
                count(DISTINCT {key_name}),
                min({key_name}),
                max({key_name})
            FROM output_{table_name}
            """
        ).fetchone()
    )


def _validate_outputs(
    connection: duckdb.DuckDBPyConnection,
    source_counts: dict[str, Any],
) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    parasha_definition = _dense_key_validation(
        connection, "parasha_definition", "parasha_definition_key"
    )
    if (
        parasha_definition[0] != parasha_definition[1]
        or parasha_definition[2] != 1
        or parasha_definition[3] != parasha_definition[0]
    ):
        raise RuntimeError(
            f"parasha definition keys are not dense: {parasha_definition}"
        )
    invalid_parasha_definition = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT
                definition.parasha_definition_key,
                definition.is_combined,
                count(member.member_index) AS member_count
            FROM output_parasha_definition AS definition
            LEFT JOIN output_parasha_definition_member AS member
              USING (parasha_definition_key)
            GROUP BY
                definition.parasha_definition_key,
                definition.is_combined
        )
        WHERE member_count NOT BETWEEN 1 AND 2
           OR is_combined <> (member_count = 2)
        """,
    )
    if invalid_parasha_definition:
        raise RuntimeError("invalid parasha definition member counts")
    combined_rows = int(
        scalar(
            connection,
            "SELECT count(*) FROM output_parasha_definition WHERE is_combined",
        )
    )
    validation["parasha_definition"] = {
        "rows": parasha_definition[0],
        "unique_keys": parasha_definition[1],
        "first_key": parasha_definition[2],
        "last_key": parasha_definition[3],
        "combined_rows": combined_rows,
        "single_rows": parasha_definition[0] - combined_rows,
        "fingerprint_sha256": _fingerprint(
            connection, "parasha_definition"
        ),
    }

    member_rows, member_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT (parasha_definition_key, member_index))
        FROM output_parasha_definition_member
        """
    ).fetchone()
    member_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_parasha_definition_member AS member
        ANTI JOIN output_parasha_definition AS definition
          USING (parasha_definition_key)
        """,
    )
    non_dense_member_groups = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT
                parasha_definition_key,
                count(*) AS rows,
                count(DISTINCT member_index) AS distinct_indexes,
                min(member_index) AS first_index,
                max(member_index) AS last_index
            FROM output_parasha_definition_member
            GROUP BY parasha_definition_key
            HAVING first_index <> 1
                OR last_index <> rows
                OR distinct_indexes <> rows
        )
        """,
    )
    rows_by_member_index = {
        str(member_index): int(rows)
        for member_index, rows in connection.execute(
            """
            SELECT member_index, count(*)
            FROM output_parasha_definition_member
            GROUP BY member_index
            ORDER BY member_index
            """
        ).fetchall()
    }
    if (
        member_rows != member_keys
        or member_orphans
        or non_dense_member_groups
    ):
        raise RuntimeError(
            "parasha member validation failed: "
            f"rows={member_rows}, unique={member_keys}, "
            f"orphans={member_orphans}, "
            f"non_dense_groups={non_dense_member_groups}"
        )
    validation["parasha_definition_member"] = {
        "rows": int(member_rows),
        "unique_keys": int(member_keys),
        "definition_orphans": int(member_orphans),
        "non_dense_index_groups": int(non_dense_member_groups),
        "rows_by_member_index": rows_by_member_index,
        "fingerprint_sha256": _fingerprint(
            connection, "parasha_definition_member"
        ),
    }

    parasha_occurrence_rows, parasha_occurrence_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT (absolute_day, schedule_key))
        FROM output_parasha_occurrence
        """
    ).fetchone()
    parasha_occurrence_orphans = connection.execute(
        """
        SELECT
            (
                SELECT count(*)
                FROM output_parasha_occurrence AS occurrence
                ANTI JOIN source_day AS day USING (absolute_day)
            ),
            (
                SELECT count(*)
                FROM output_parasha_occurrence AS occurrence
                ANTI JOIN output_parasha_definition AS definition
                  USING (parasha_definition_key)
            ),
            (
                SELECT count(*)
                FROM output_parasha_occurrence AS occurrence
                ANTI JOIN source_day_schedule AS schedule
                  ON occurrence.absolute_day = schedule.absolute_day
                 AND occurrence.schedule_key = CASE schedule.schedule
                     WHEN 'diaspora' THEN 0
                     WHEN 'israel' THEN 1
                 END
            )
        """
    ).fetchone()
    if (
        parasha_occurrence_rows
        != source_counts["core_parasha_occurrence_rows"]
        or parasha_occurrence_rows != parasha_occurrence_keys
        or any(parasha_occurrence_orphans)
    ):
        raise RuntimeError(
            "parasha occurrence validation failed: "
            f"rows={parasha_occurrence_rows}, "
            f"unique={parasha_occurrence_keys}, "
            f"source={source_counts['core_parasha_occurrence_rows']}, "
            f"orphans={parasha_occurrence_orphans}"
        )
    parasha_rows_by_schedule = _rows_by_schedule_key(
        connection, "output_parasha_occurrence"
    )
    if (
        parasha_rows_by_schedule
        != source_counts["core_parasha_occurrence_rows_by_schedule"]
    ):
        raise RuntimeError("parasha occurrence schedule split changed")
    validation["parasha_occurrence"] = {
        "rows": int(parasha_occurrence_rows),
        "unique_keys": int(parasha_occurrence_keys),
        "rows_by_schedule": parasha_rows_by_schedule,
        "used_definition_count": int(
            scalar(
                connection,
                """
                SELECT count(DISTINCT parasha_definition_key)
                FROM output_parasha_occurrence
                """,
            )
        ),
        "day_orphans": int(parasha_occurrence_orphans[0]),
        "definition_orphans": int(parasha_occurrence_orphans[1]),
        "schedule_orphans": int(parasha_occurrence_orphans[2]),
    }

    leyning_definition = _dense_key_validation(
        connection,
        "leyning_reading_definition",
        "reading_definition_key",
    )
    if (
        leyning_definition[0] != leyning_definition[1]
        or leyning_definition[2] != 1
        or leyning_definition[3] != leyning_definition[0]
        or scalar(
            connection,
            """
            SELECT count(*)
            FROM output_leyning_reading_definition
            WHERE source_payload_sha256 IS NULL
               OR reading_type IS NULL
               OR name_en IS NULL
               OR name_he IS NULL
            """,
        )
    ):
        raise RuntimeError(
            f"leyning definition validation failed: {leyning_definition}"
        )
    rows_by_type = {
        str(reading_type): int(rows)
        for reading_type, rows in connection.execute(
            """
            SELECT reading_type, count(*)
            FROM output_leyning_reading_definition
            GROUP BY reading_type
            ORDER BY reading_type
            """
        ).fetchall()
    }
    unique_payload_hashes, null_summary, null_summary_he, null_summary_ashkenazi = (
        connection.execute(
            """
            SELECT
                count(DISTINCT source_payload_sha256),
                count(*) FILTER (WHERE summary IS NULL),
                count(*) FILTER (WHERE summary_he IS NULL),
                count(*) FILTER (WHERE summary_ashkenazi IS NULL)
            FROM output_leyning_reading_definition
            """
        ).fetchone()
    )
    validation["leyning_reading_definition"] = {
        "rows": leyning_definition[0],
        "unique_keys": leyning_definition[1],
        "unique_payload_hashes": int(unique_payload_hashes),
        "first_key": leyning_definition[2],
        "last_key": leyning_definition[3],
        "rows_by_type": rows_by_type,
        "null_summaries": {
            "summary": int(null_summary),
            "summary_he": int(null_summary_he),
            "summary_ashkenazi": int(null_summary_ashkenazi),
        },
        "fingerprint_sha256": _fingerprint(
            connection, "leyning_reading_definition"
        ),
    }

    leyning_parasha_rows, leyning_parasha_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT (reading_definition_key, member_index))
        FROM output_leyning_definition_parasha
        """
    ).fetchone()
    leyning_parasha_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_leyning_definition_parasha AS member
        ANTI JOIN output_leyning_reading_definition AS definition
          USING (reading_definition_key)
        """,
    )
    leyning_parasha_non_dense = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT
                reading_definition_key,
                count(*) AS rows,
                count(DISTINCT member_index) AS distinct_indexes,
                min(member_index) AS first_index,
                max(member_index) AS last_index
            FROM output_leyning_definition_parasha
            GROUP BY reading_definition_key
            HAVING first_index <> 1
                OR last_index <> rows
                OR distinct_indexes <> rows
        )
        """,
    )
    leyning_parasha_mapping_conflicts = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT parasha_name
            FROM output_leyning_definition_parasha
            GROUP BY parasha_name
            HAVING count(DISTINCT parasha_number) <> 1
            UNION ALL
            SELECT CAST(parasha_number AS VARCHAR)
            FROM output_leyning_definition_parasha
            GROUP BY parasha_number
            HAVING count(DISTINCT parasha_name) <> 1
        )
        """,
    )
    if (
        leyning_parasha_rows != leyning_parasha_keys
        or leyning_parasha_orphans
        or leyning_parasha_non_dense
        or leyning_parasha_mapping_conflicts
    ):
        raise RuntimeError("leyning parasha bridge validation failed")
    rows_by_leyning_member_index = {
        str(member_index): int(rows)
        for member_index, rows in connection.execute(
            """
            SELECT member_index, count(*)
            FROM output_leyning_definition_parasha
            GROUP BY member_index
            ORDER BY member_index
            """
        ).fetchall()
    }
    first_parasha_number, last_parasha_number = connection.execute(
        """
        SELECT min(parasha_number), max(parasha_number)
        FROM output_leyning_definition_parasha
        """
    ).fetchone()
    validation["leyning_definition_parasha"] = {
        "rows": int(leyning_parasha_rows),
        "unique_keys": int(leyning_parasha_keys),
        "rows_by_member_index": rows_by_leyning_member_index,
        "represented_definition_count": int(
            scalar(
                connection,
                """
                SELECT count(DISTINCT reading_definition_key)
                FROM output_leyning_definition_parasha
                """,
            )
        ),
        "first_parasha_number": int(first_parasha_number),
        "last_parasha_number": int(last_parasha_number),
        "definition_orphans": int(leyning_parasha_orphans),
        "non_dense_index_groups": int(leyning_parasha_non_dense),
        "mapping_conflicts": int(leyning_parasha_mapping_conflicts),
        "fingerprint_sha256": _fingerprint(
            connection, "leyning_definition_parasha"
        ),
    }

    segment_rows, segment_keys = connection.execute(
        """
        SELECT
            count(*),
            count(
                DISTINCT (
                    reading_definition_key,
                    segment_kind,
                    segment_index
                )
            )
        FROM output_leyning_segment_definition
        """
    ).fetchone()
    segment_orphans = scalar(
        connection,
        """
        SELECT count(*)
        FROM output_leyning_segment_definition AS segment
        ANTI JOIN output_leyning_reading_definition AS definition
          USING (reading_definition_key)
        """,
    )
    rows_by_kind = {
        str(segment_kind): int(rows)
        for segment_kind, rows in connection.execute(
            """
            SELECT segment_kind, count(*)
            FROM output_leyning_segment_definition
            GROUP BY segment_kind
            ORDER BY segment_kind
            """
        ).fetchall()
    }
    max_index_by_kind = {
        str(segment_kind): int(max_index)
        for segment_kind, max_index in connection.execute(
            """
            SELECT segment_kind, max(segment_index)
            FROM output_leyning_segment_definition
            GROUP BY segment_kind
            ORDER BY segment_kind
            """
        ).fetchall()
    }
    (
        null_verse_count_rows,
        null_parasha_number_rows,
        populated_reason_rows,
        populated_note_rows,
    ) = connection.execute(
        """
        SELECT
            count(*) FILTER (WHERE verse_count IS NULL),
            count(*) FILTER (WHERE parasha_number IS NULL),
            count(*) FILTER (WHERE reason_en IS NOT NULL),
            count(*) FILTER (WHERE note_en IS NOT NULL)
        FROM output_leyning_segment_definition
        """
    ).fetchone()
    non_dense_segment_groups = scalar(
        connection,
        """
        SELECT count(*)
        FROM (
            SELECT
                reading_definition_key,
                segment_kind,
                count(*) AS rows,
                count(DISTINCT segment_index) AS distinct_indexes,
                min(segment_index) AS first_index,
                max(segment_index) AS last_index
            FROM output_leyning_segment_definition
            GROUP BY reading_definition_key, segment_kind
            HAVING first_index <> 1
                OR last_index <> rows
                OR distinct_indexes <> rows
        )
        """,
    )
    if (
        segment_rows != segment_keys
        or segment_orphans
        or non_dense_segment_groups
        or not rows_by_kind
        or not set(rows_by_kind).issubset(SEGMENT_KINDS)
    ):
        raise RuntimeError(
            "leyning segment validation failed: "
            f"rows={segment_rows}, unique={segment_keys}, "
            f"orphans={segment_orphans}, "
            f"non_dense_groups={non_dense_segment_groups}, "
            f"kinds={rows_by_kind}"
        )
    validation["leyning_segment_definition"] = {
        "rows": int(segment_rows),
        "unique_keys": int(segment_keys),
        "rows_by_kind": rows_by_kind,
        "max_index_by_kind": max_index_by_kind,
        "null_verse_count_rows": int(null_verse_count_rows),
        "null_parasha_number_rows": int(null_parasha_number_rows),
        "populated_reason_rows": int(populated_reason_rows),
        "populated_note_rows": int(populated_note_rows),
        "definition_orphans": int(segment_orphans),
        "non_dense_index_groups": int(non_dense_segment_groups),
        "fingerprint_sha256": _fingerprint(
            connection, "leyning_segment_definition"
        ),
    }

    leyning_occurrence_rows, leyning_occurrence_keys = connection.execute(
        """
        SELECT
            count(*),
            count(DISTINCT (absolute_day, schedule_key, reading_index))
        FROM output_leyning_occurrence
        """
    ).fetchone()
    leyning_occurrence_orphans = connection.execute(
        """
        SELECT
            (
                SELECT count(*)
                FROM output_leyning_occurrence AS occurrence
                ANTI JOIN source_day AS day USING (absolute_day)
            ),
            (
                SELECT count(*)
                FROM output_leyning_occurrence AS occurrence
                ANTI JOIN output_leyning_reading_definition AS definition
                  USING (reading_definition_key)
            ),
            (
                SELECT count(*)
                FROM output_leyning_occurrence AS occurrence
                ANTI JOIN source_day_schedule AS schedule
                  ON occurrence.absolute_day = schedule.absolute_day
                 AND occurrence.schedule_key = CASE schedule.schedule
                     WHEN 'diaspora' THEN 0
                     WHEN 'israel' THEN 1
                 END
            )
        """
    ).fetchone()
    if (
        leyning_occurrence_rows
        != source_counts["core_leyning_occurrence_rows"]
        or leyning_occurrence_rows != leyning_occurrence_keys
        or any(leyning_occurrence_orphans)
    ):
        raise RuntimeError(
            "leyning occurrence validation failed: "
            f"rows={leyning_occurrence_rows}, "
            f"unique={leyning_occurrence_keys}, "
            f"source={source_counts['core_leyning_occurrence_rows']}, "
            f"orphans={leyning_occurrence_orphans}"
        )
    leyning_rows_by_schedule = _rows_by_schedule_key(
        connection, "output_leyning_occurrence"
    )
    if (
        leyning_rows_by_schedule
        != source_counts["core_leyning_occurrence_rows_by_schedule"]
    ):
        raise RuntimeError("leyning occurrence schedule split changed")
    validation["leyning_occurrence"] = {
        "rows": int(leyning_occurrence_rows),
        "unique_keys": int(leyning_occurrence_keys),
        "rows_by_schedule": leyning_rows_by_schedule,
        "rows_by_reading_index": {
            str(reading_index): int(rows)
            for reading_index, rows in connection.execute(
                """
                SELECT reading_index, count(*)
                FROM output_leyning_occurrence
                GROUP BY reading_index
                ORDER BY reading_index
                """
            ).fetchall()
        },
        "used_definition_count": int(
            scalar(
                connection,
                """
                SELECT count(DISTINCT reading_definition_key)
                FROM output_leyning_occurrence
                """,
            )
        ),
        "day_orphans": int(leyning_occurrence_orphans[0]),
        "definition_orphans": int(leyning_occurrence_orphans[1]),
        "schedule_orphans": int(leyning_occurrence_orphans[2]),
    }

    return validation


def _validate_official_materialization(
    source_manifest_hash: str, validation: dict[str, Any]
) -> bool:
    if source_manifest_hash != OFFICIAL_CORPUS_MANIFEST_SHA256:
        return False
    for table_name, expected_values in OFFICIAL_VALIDATION.items():
        actual_values = validation[table_name]
        for key, expected in expected_values.items():
            if actual_values.get(key) != expected:
                raise RuntimeError(
                    f"official {table_name}.{key} mismatch: "
                    f"expected={expected}, actual={actual_values.get(key)}"
                )
    for table_name, expected in OFFICIAL_FINGERPRINTS.items():
        if not expected:
            raise RuntimeError(
                f"official fingerprint is not frozen for {table_name}"
            )
        actual = validation[table_name]["fingerprint_sha256"]
        if actual != expected:
            raise RuntimeError(
                f"official {table_name} fingerprint mismatch: "
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
            f"{output_root} already exists; "
            f"{MATERIALIZATION_VERSION} cannot be rewritten"
        )
    if output_root == corpus_root or corpus_root in output_root.parents:
        raise ValueError(
            "the readings materialization cannot be written inside corpus-v1"
        )

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
                "threads": 1,
            },
            "keys": {
                "schedule_key": SCHEDULE_KEYS,
                "parasha_definition_key": {
                    "base": 1,
                    "dense": True,
                    "sort": "UTF-8 byte order of ordered parasha members",
                },
                "reading_definition_key": {
                    "base": 1,
                    "dense": True,
                    "sort": "source_payload_sha256 ascending",
                },
            },
            "json_contract": {
                "recognized_root_keys": sorted(JSON_ROOT_KEYS),
                "recognized_segment_kinds": sorted(SEGMENT_KINDS),
                "unknown_root_or_path_behavior": "fail",
                "locale_structure_alignment_required": True,
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
