from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

import materialize_powerbi_compatibility as compatibility


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CompatibilityMaterializationTests(unittest.TestCase):
    def make_snapshot(self, root: Path) -> Path:
        snapshot = root / "snapshot"
        snapshot.mkdir()
        rows = []
        for index, date in enumerate(("2026-01-01T00:00:00", "2026-01-02T00:00:00")):
            row = {name: None for name, _ in compatibility.EXPECTED_COLUMNS}
            row.update(
                {
                    "Date": date,
                    "Hebrew Date": f"legacy date {index + 1}",
                    "Hebrew Year": 5786,
                    "Hebrew Day of Month": index + 12,
                    "Hebrew Month": "Teves",
                    "Category": "" if index == 0 else None,
                }
            )
            rows.append(row)

        source_path = snapshot / compatibility.SOURCE_FILE_NAME
        with source_path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                json.dump(row, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")

        schema = {
            "snapshot_version": "hebcal-compatibility-source-v1",
            "table_name": "Hebcal",
            "row_count": len(rows),
            "columns": [
                {
                    "name": name,
                    "source_column": name,
                    "data_type": data_type,
                }
                for name, data_type in compatibility.EXPECTED_COLUMNS
            ],
            "exporter_script_sha256": "c" * 64,
            "tmdl_sha256": "a" * 64,
            "dax_query_sha256": "b" * 64,
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
            "source_jsonl_sha256": file_hash(source_path),
            "schema_sha256": file_hash(schema_path),
        }
        (snapshot / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return snapshot

    def test_materializes_exact_contract_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            before = {
                path.name: file_hash(path)
                for path in snapshot.iterdir()
                if path.is_file()
            }
            output = root / "output"

            manifest_path = compatibility.materialize(snapshot, output)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["validation"]["rows"], 2)
            self.assertEqual(manifest["validation"]["unique_dates"], 2)
            self.assertEqual(manifest["validation"]["date_gaps"], 0)
            self.assertEqual(
                manifest["validation"]["source_minus_output_rows"], 0
            )
            self.assertEqual(
                manifest["validation"]["output_minus_source_rows"], 0
            )
            self.assertFalse(manifest["official_legacy_baseline_verified"])
            parquet = output / compatibility.OUTPUT_FILE_NAME
            with duckdb.connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT count(*)
                    FROM read_parquet(
                        {compatibility.sql_literal(parquet)},
                        hive_partitioning = false
                    )
                    """
                ).fetchone()[0]
                names = [
                    row[0]
                    for row in connection.execute(
                        f"""
                        DESCRIBE SELECT *
                        FROM read_parquet(
                            {compatibility.sql_literal(parquet)},
                            hive_partitioning = false
                        )
                        """
                    ).fetchall()
                ]
                blank_categories, null_categories = connection.execute(
                    f"""
                    SELECT
                        count(*) FILTER (WHERE "Category" = ''),
                        count(*) FILTER (WHERE "Category" IS NULL)
                    FROM read_parquet(
                        {compatibility.sql_literal(parquet)},
                        hive_partitioning = false
                    )
                    """
                ).fetchone()
            self.assertEqual(rows, 2)
            self.assertEqual((blank_categories, null_categories), (1, 1))
            self.assertEqual(
                names,
                [name for name, _ in compatibility.EXPECTED_COLUMNS],
            )
            after = {
                path.name: file_hash(path)
                for path in snapshot.iterdir()
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
                compatibility.materialize(snapshot, output)

    def test_rejects_changed_column_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            schema_path = snapshot / "schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            schema["columns"][0]["name"] = "Changed Date"
            schema_path.write_text(
                json.dumps(schema, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            provenance_path = snapshot / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["schema_sha256"] = file_hash(schema_path)
            provenance_path.write_text(
                json.dumps(provenance, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(RuntimeError, "87-column contract"):
                compatibility.materialize(snapshot, root / "output")

    def test_rejects_provenance_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = self.make_snapshot(root)
            source_path = snapshot / compatibility.SOURCE_FILE_NAME
            source_path.write_text(
                source_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(RuntimeError, "JSONL source"):
                compatibility.materialize(snapshot, root / "output")


if __name__ == "__main__":
    unittest.main()
