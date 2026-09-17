from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import duckdb

import materialize_powerbi_zmanim as zmanim


class ZmanimMaterializationTests(unittest.TestCase):
    def test_small_range_is_complete_and_has_shifted_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            manifest_path = zmanim.materialize(
                output,
                "2026-08-01",
                "2026-08-10",
                compatibility_path=None,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["validation"]["dates"], 10)
            self.assertEqual(manifest["validation"]["variables"], 25)
            self.assertEqual(manifest["validation"]["rows"], 250)
            with duckdb.connect() as connection:
                values = connection.execute(
                    """
                    SELECT Value, Value_Yesterday, Value_OneWeekAgo
                    FROM read_parquet(?)
                    WHERE Date = DATE '2026-08-10' AND Variable = 'sunrise'
                    """,
                    [str(output / "zmanim.parquet")],
                ).fetchone()
                self.assertIsNotNone(values[0])
                self.assertIsNotNone(values[1])
                self.assertIsNotNone(values[2])

    def test_refuses_to_replace_immutable_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            (output / "existing.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                zmanim.materialize(
                    output,
                    "2026-08-10",
                    "2026-08-10",
                    compatibility_path=None,
                )


if __name__ == "__main__":
    unittest.main()
