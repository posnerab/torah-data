#!/usr/bin/env python3
"""Land curated Power BI tables as an immutable, deterministic Parquet v1."""

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
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data" / "powerbi-static-v1"

SNAPSHOT_VERSION = "powerbi-static-source-v1"
MATERIALIZATION_VERSION = "powerbi-static-v1"
TARGET_TABLES = (
    ("Holidays", "holidays"),
    ("Pasukim", "pasukim"),
    ("Parashiyos", "parashiyos"),
    ("Fast Days", "fast_days"),
    ("Haftaros", "haftaros"),
    ("Parasha-Mitzvos", "parasha_mitzvos"),
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


def text_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _require_checksum(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeError(f"{label} is not a lowercase SHA-256 checksum")
    return value


def _verify_snapshot(
    snapshot_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str]:
    schema_path = snapshot_root / "schema.json"
    provenance_path = snapshot_root / "provenance.json"
    for path in (schema_path, provenance_path):
        if not path.is_file():
            raise FileNotFoundError(f"static snapshot is missing {path.name}")

    schema = load_json(schema_path)
    provenance = load_json(provenance_path)
    schema_hash = sha256(schema_path)
    if schema.get("snapshot_version") != SNAPSHOT_VERSION:
        raise RuntimeError("unexpected static snapshot version")
    if provenance.get("schema_sha256") != schema_hash:
        raise RuntimeError("snapshot provenance does not match schema.json")
    exporter_hash = _require_checksum(
        schema.get("exporter_script_sha256"), "exporter_script_sha256"
    )

    expected_order = [name for name, _ in TARGET_TABLES]
    if schema.get("table_order") != expected_order:
        raise RuntimeError("snapshot does not contain the exact target table order")
    tables = schema.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(expected_order):
        raise RuntimeError("snapshot does not contain the exact target table set")
    source_files = provenance.get("source_files")
    if not isinstance(source_files, dict):
        raise RuntimeError("snapshot provenance has no source_files")

    verified: list[dict[str, Any]] = []
    expected_source_files: set[str] = set()
    total_rows = 0
    for table_name, slug in TARGET_TABLES:
        table = tables[table_name]
        if not isinstance(table, dict) or table.get("slug") != slug:
            raise RuntimeError(f"{table_name} has an invalid snapshot slug")
        relative_source = f"tables/{slug}.jsonl"
        if table.get("source_file") != relative_source:
            raise RuntimeError(f"{table_name} has an invalid source file")
        expected_source_files.add(relative_source)
        source_path = snapshot_root / "tables" / f"{slug}.jsonl"
        if not source_path.is_file():
            raise FileNotFoundError(f"static snapshot is missing {relative_source}")

        try:
            row_count = int(table["row_count"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"{table_name} has no valid row count") from error
        if row_count <= 0:
            raise RuntimeError(f"{table_name} has no rows")
        total_rows += row_count

        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            raise RuntimeError(f"{table_name} has no imported-column contract")
        names: list[str] = []
        seen_names: set[str] = set()
        normalized_columns: list[dict[str, str]] = []
        for column in columns:
            if not isinstance(column, dict):
                raise RuntimeError(f"{table_name} has an invalid column entry")
            name = column.get("name")
            source_column = column.get("source_column")
            data_type = column.get("data_type")
            if not isinstance(name, str) or not name:
                raise RuntimeError(f"{table_name} has an unnamed column")
            if name.casefold() in seen_names:
                raise RuntimeError(f"{table_name} has duplicate column {name!r}")
            seen_names.add(name.casefold())
            if not isinstance(source_column, str) or not source_column:
                raise RuntimeError(f"{table_name}[{name}] has no sourceColumn")
            if data_type not in DUCKDB_TYPES:
                raise RuntimeError(
                    f"{table_name}[{name}] has unsupported type {data_type!r}"
                )
            names.append(name)
            normalized_columns.append(
                {
                    "name": name,
                    "source_column": source_column,
                    "data_type": data_type,
                }
            )
        if table.get("order_by") != names:
            raise RuntimeError(f"{table_name} is not ordered by its full contract")
        tmdl_hash = _require_checksum(
            table.get("tmdl_sha256"), f"{table_name} tmdl_sha256"
        )
        dax_hash = _require_checksum(
            table.get("dax_query_sha256"), f"{table_name} dax_query_sha256"
        )

        file_provenance = source_files.get(relative_source)
        if not isinstance(file_provenance, dict):
            raise RuntimeError(f"{relative_source} has no provenance")
        source_hash = sha256(source_path)
        if file_provenance.get("sha256") != source_hash:
            raise RuntimeError(f"snapshot provenance does not match {relative_source}")
        if int(file_provenance.get("bytes", -1)) != source_path.stat().st_size:
            raise RuntimeError(f"snapshot byte count does not match {relative_source}")
        if int(file_provenance.get("rows", -1)) != row_count:
            raise RuntimeError(f"snapshot row count does not match {relative_source}")

        verified.append(
            {
                "name": table_name,
                "slug": slug,
                "source_path": source_path,
                "source_file": relative_source,
                "source_sha256": source_hash,
                "row_count": row_count,
                "columns": normalized_columns,
                "contract_sha256": text_sha256(normalized_columns),
                "tmdl_sha256": tmdl_hash,
                "dax_query_sha256": dax_hash,
            }
        )

    if set(source_files) != expected_source_files:
        raise RuntimeError("snapshot provenance contains an unexpected source file")
    if int(schema.get("total_rows", -1)) != total_rows:
        raise RuntimeError("snapshot total_rows does not match its tables")
    return schema, provenance, verified, schema_hash


def _json_columns_sql(columns: list[dict[str, str]]) -> str:
    members = ", ".join(
        f"{sql_literal(column['name'])}: "
        f"{sql_literal(DUCKDB_TYPES[column['data_type']])}"
        for column in columns
    )
    return "{" + members + "}"


def _selected_columns(columns: list[dict[str, str]]) -> str:
    return ", ".join(sql_identifier(column["name"]) for column in columns)


def _order_by(columns: list[dict[str, str]]) -> str:
    return ", ".join(
        f"{sql_identifier(column['name'])} ASC NULLS FIRST"
        for column in columns
    )


def _create_source_view(
    connection: duckdb.DuckDBPyConnection, table: dict[str, Any]
) -> str:
    view_name = f"source_{table['slug']}"
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW {sql_identifier(view_name)} AS
        SELECT *
        FROM read_json(
            {sql_literal(table["source_path"])},
            format = 'newline_delimited',
            columns = {_json_columns_sql(table["columns"])}
        )
        """
    )
    return view_name


def _parquet_columns(path: Path) -> list[dict[str, str]]:
    with duckdb.connect() as connection:
        rows = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_literal(path)})"
        ).fetchall()
    return [
        {"name": row[0], "type": row[1], "nullable": row[2]}
        for row in rows
    ]


def _land_table(
    connection: duckdb.DuckDBPyConnection,
    table: dict[str, Any],
    output_path: Path,
) -> dict[str, int]:
    view_name = _create_source_view(connection, table)
    view = sql_identifier(view_name)
    rows = connection.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
    if rows != table["row_count"]:
        raise RuntimeError(
            f"{table['name']} row count mismatch: "
            f"schema={table['row_count']}, data={rows}"
        )

    selected = _selected_columns(table["columns"])
    connection.execute(
        f"""
        COPY (
            SELECT {selected}
            FROM {view}
            ORDER BY {_order_by(table["columns"])}
        )
        TO {sql_literal(output_path)}
        (
            FORMAT PARQUET,
            COMPRESSION ZSTD,
            ROW_GROUP_SIZE 100000
        )
        """
    )
    output = (
        f"read_parquet({sql_literal(output_path)}, "
        "hive_partitioning = false)"
    )
    source_minus_output = connection.execute(
        f"""
        SELECT count(*)
        FROM (
            (SELECT {selected} FROM {view})
            EXCEPT ALL
            (SELECT {selected} FROM {output})
        )
        """
    ).fetchone()[0]
    output_minus_source = connection.execute(
        f"""
        SELECT count(*)
        FROM (
            (SELECT {selected} FROM {output})
            EXCEPT ALL
            (SELECT {selected} FROM {view})
        )
        """
    ).fetchone()[0]
    if source_minus_output or output_minus_source:
        raise RuntimeError(
            f"{table['name']} Parquet changed source values: "
            f"source_minus_output={source_minus_output}, "
            f"output_minus_source={output_minus_source}"
        )
    output_rows = connection.execute(
        f"SELECT count(*) FROM {output}"
    ).fetchone()[0]
    return {
        "source_rows": int(rows),
        "output_rows": int(output_rows),
        "source_minus_output_rows": int(source_minus_output),
        "output_minus_source_rows": int(output_minus_source),
    }


def materialize(snapshot_root: Path, output_root: Path) -> Path:
    snapshot_root = snapshot_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(
            f"{output_root} already exists; "
            f"{MATERIALIZATION_VERSION} cannot be rewritten"
        )
    if output_root == snapshot_root or snapshot_root in output_root.parents:
        raise ValueError("static output cannot be inside its source snapshot")

    schema, source_provenance, tables, schema_hash = _verify_snapshot(
        snapshot_root
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent)
    )
    artifact_root = workspace / "artifact"
    artifact_tables = artifact_root / "tables"
    artifact_tables.mkdir(parents=True)
    try:
        duckdb_temp = workspace / "duckdb-temp"
        duckdb_temp.mkdir()
        table_manifest: dict[str, Any] = {}
        with duckdb.connect() as connection:
            connection.execute("SET threads = 1")
            connection.execute("SET default_collation = ''")
            connection.execute("SET preserve_insertion_order = true")
            connection.execute(f"SET temp_directory = {sql_literal(duckdb_temp)}")
            for table in tables:
                relative_output = f"tables/{table['slug']}.parquet"
                output_path = artifact_tables / f"{table['slug']}.parquet"
                validation = _land_table(connection, table, output_path)
                table_manifest[table["name"]] = {
                    "slug": table["slug"],
                    "source": {
                        "file": table["source_file"],
                        "jsonl_sha256": table["source_sha256"],
                        "tmdl_sha256": table["tmdl_sha256"],
                        "dax_query_sha256": table["dax_query_sha256"],
                        "contract_sha256": table["contract_sha256"],
                    },
                    "columns": table["columns"],
                    "ordering": [column["name"] for column in table["columns"]],
                    "file": {
                        "path": relative_output,
                        "bytes": output_path.stat().st_size,
                        "sha256": sha256(output_path),
                        "rows": validation["output_rows"],
                        "columns": _parquet_columns(output_path),
                    },
                    "validation": validation,
                }

        manifest = {
            "materialization_version": MATERIALIZATION_VERSION,
            "status": "complete-immutable-derived",
            "source": {
                "kind": "power-bi-semantic-model-snapshot",
                "snapshot_version": schema["snapshot_version"],
                "schema_sha256": schema_hash,
                "exporter_script_sha256": schema["exporter_script_sha256"],
            },
            "builder": {
                "script_sha256": sha256(Path(__file__).resolve()),
                "duckdb_version": duckdb.__version__,
            },
            "table_order": [name for name, _ in TARGET_TABLES],
            "tables": table_manifest,
            "validation": {
                "tables": len(tables),
                "source_rows": sum(
                    table["row_count"] for table in tables
                ),
                "output_rows": sum(
                    value["validation"]["output_rows"]
                    for value in table_manifest.values()
                ),
                "source_minus_output_rows": sum(
                    value["validation"]["source_minus_output_rows"]
                    for value in table_manifest.values()
                ),
                "output_minus_source_rows": sum(
                    value["validation"]["output_minus_source_rows"]
                    for value in table_manifest.values()
                ),
            },
            "immutability": {
                "overwrite_existing_output": False,
                "source_snapshot_modified": False,
                "changed_projection_requires_new_version": True,
            },
        }
        manifest_path = artifact_root / "manifest.json"
        write_json_exclusive(manifest_path, manifest)
        manifest_hash = sha256(manifest_path)
        provenance = {
            "created_utc": datetime.now(UTC).isoformat(),
            "content_manifest_sha256": manifest_hash,
            "materialization_id": f"sha256:{manifest_hash}",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        required=True,
        help="disposable source directory written by the Power BI exporter",
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
