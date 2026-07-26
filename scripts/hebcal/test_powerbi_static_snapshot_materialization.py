from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

import materialize_powerbi_static_snapshots as static_snapshots


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StaticSnapshotMaterializationTests(unittest.TestCase):
    columns = [
        {"name": "Label", "source_column": "Label", "data_type": "string"},
        {"name": "Ordinal", "source_column": "Ordinal", "data_type": "int64"},
        {"name": "Moment", "source_column": "Moment", "data_type": "dateTime"},
        {"name": "Flag", "source_column": "Flag", "data_type": "boolean"},
        {"name": "Ratio", "source_column": "Ratio", "data_type": "double"},
    ]

    def make_snapshot(self, root: Path) -> Path:
        snapshot = root / "snapshot"
        tables_root = snapshot / "tables"
        tables_root.mkdir(parents=True)
        table_schemas = {}
        source_files = {}
        total_rows = 0
        for index, (table_name, slug) in enumerate(
            static_snapshots.TARGET_TABLES
        ):
            rows = [
                {
                    "Label": None,
                    "Ordinal": 2,
                    "Moment": "2026-01-02T00:00:00",
                    "Flag": False,
                    "Ratio": index + 0.5,
                },
                {
                    "Label": "",
                    "Ordinal": 1,
                    "Moment": "2026-01-01T00:00:00",
                    "Flag": True,
                    "Ratio": None,
                },
            ]
            relative_source = f"tables/{slug}.jsonl"
            source_path = tables_root / f"{slug}.jsonl"
            with source_path.open("w", encoding="utf-8", newline="\n") as handle:
                for row in rows:
                    json.dump(
                        row,
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    handle.write("\n")
            table_schemas[table_name] = {
                "slug": slug,
                "source_file": relative_source,
                "row_count": len(rows),
                "columns": self.columns,
                "order_by": [column["name"] for column in self.columns],
                "tmdl_sha256": "a" * 64,
                "dax_query_sha256": "b" * 64,
            }
            source_files[relative_source] = {
                "bytes": source_path.stat().st_size,
                "sha256": file_hash(source_path),
                "rows": len(rows),
            }
            total_rows += len(rows)

        schema = {
            "snapshot_version": static_snapshots.SNAPSHOT_VERSION,
            "exporter_script_sha256": "c" * 64,
            "table_order": [
                name for name, _ in static_snapshots.TARGET_TABLES
            ],
            "total_rows": total_rows,
            "tables": table_schemas,
        }
        schema_path = snapshot / "schema.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        provenance = {
            "exported_utc": "2026-01-01T00:00:00Z",
            "data_source": "localhost:12345",
            "database": "test-model",
            "schema_sha256": file_hash(schema_path),
            "source_files": source_files,
        }
        (snapshot / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return snapshot

    def test_materializes_all_tables_exactly_and_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            before = {
                str(path.relative_to(snapshot)): file_hash(path)
                for path in snapshot.rglob("*")
                if path.is_file()
            }

            first_manifest_path = static_snapshots.materialize(
                snapshot, root / "output-one"
            )
            second_manifest_path = static_snapshots.materialize(
                snapshot, root / "output-two"
            )
            first_manifest = json.loads(
                first_manifest_path.read_text(encoding="utf-8")
            )
            second_manifest = json.loads(
                second_manifest_path.read_text(encoding="utf-8")
            )

            self.assertEqual(first_manifest["validation"]["tables"], 6)
            self.assertEqual(first_manifest["validation"]["source_rows"], 12)
            self.assertEqual(first_manifest["validation"]["output_rows"], 12)
            self.assertEqual(
                first_manifest["validation"]["source_minus_output_rows"], 0
            )
            self.assertEqual(
                first_manifest["validation"]["output_minus_source_rows"], 0
            )
            self.assertEqual(file_hash(first_manifest_path), file_hash(second_manifest_path))

            for table_name, slug in static_snapshots.TARGET_TABLES:
                first_parquet = root / "output-one" / "tables" / f"{slug}.parquet"
                second_parquet = root / "output-two" / "tables" / f"{slug}.parquet"
                self.assertEqual(file_hash(first_parquet), file_hash(second_parquet))
                self.assertEqual(
                    first_manifest["tables"][table_name]["file"]["sha256"],
                    second_manifest["tables"][table_name]["file"]["sha256"],
                )
                with duckdb.connect() as connection:
                    rows, blanks, nulls = connection.execute(
                        f"""
                        SELECT
                            count(*),
                            count(*) FILTER (WHERE "Label" = ''),
                            count(*) FILTER (WHERE "Label" IS NULL)
                        FROM read_parquet(
                            {static_snapshots.sql_literal(first_parquet)},
                            hive_partitioning = false
                        )
                        """
                    ).fetchone()
                self.assertEqual((rows, blanks, nulls), (2, 1, 1))

            after = {
                str(path.relative_to(snapshot)): file_hash(path)
                for path in snapshot.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            output = root / "output"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                static_snapshots.materialize(snapshot, output)

    def test_rejects_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            source = snapshot / "tables" / "holidays.jsonl"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(RuntimeError, "holidays.jsonl"):
                static_snapshots.materialize(snapshot, root / "output")


if __name__ == "__main__":
    unittest.main()
