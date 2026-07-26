import tempfile
import unittest
from pathlib import Path

import duckdb

from materialize_powerbi import (
    OUTPUT_TABLE_FILES,
    load_json,
    materialize,
    sha256,
    sql_literal,
    write_json_exclusive,
)


class PowerBiMaterializationTests(unittest.TestCase):
    def _write_fixture(self, root: Path, *, orphan_event: bool = False) -> Path:
        corpus_root = root / "corpus-v1"
        partition_root = corpus_root / "block=0001-0001"
        partition_root.mkdir(parents=True)

        day_path = partition_root / "core_day.parquet"
        schedule_path = partition_root / "core_day_schedule.parquet"
        event_path = partition_root / "core_event_occurrence.parquet"
        event_day = 99 if orphan_event else 11
        with duckdb.connect() as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM (VALUES (10::INTEGER), (11::INTEGER))
                        AS rows(absolute_day)
                    ORDER BY absolute_day
                )
                TO {sql_literal(day_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM (
                        VALUES
                            (
                                10::INTEGER,
                                'diaspora'::VARCHAR,
                                0::SMALLINT,
                                '{{"allCongs":true,"mincha":true,"shacharit":true}}'::VARCHAR,
                                true::BOOLEAN,
                                false::BOOLEAN
                            ),
                            (
                                10::INTEGER,
                                'israel'::VARCHAR,
                                1::SMALLINT,
                                '{{"allCongs":false,"mincha":false,"shacharit":true}}'::VARCHAR,
                                true::BOOLEAN,
                                false::BOOLEAN
                            ),
                            (
                                11::INTEGER,
                                'diaspora'::VARCHAR,
                                2::SMALLINT,
                                NULL::VARCHAR,
                                false::BOOLEAN,
                                true::BOOLEAN
                            ),
                            (
                                11::INTEGER,
                                'israel'::VARCHAR,
                                2::SMALLINT,
                                NULL::VARCHAR,
                                false::BOOLEAN,
                                true::BOOLEAN
                            )
                    ) AS rows(
                        absolute_day,
                        schedule,
                        hallel,
                        tachanun_json,
                        tachanun_supported,
                        eruv_tavshilin
                    )
                    ORDER BY absolute_day, schedule
                )
                TO {sql_literal(schedule_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT *
                    FROM (
                        VALUES
                            (
                                10::INTEGER,
                                'diaspora'::VARCHAR,
                                'Holiday'::VARCHAR,
                                'Zeta'::VARCHAR,
                                'zeta'::VARCHAR,
                                2::INTEGER,
                                'Zeta'::VARCHAR,
                                'זטא'::VARCHAR,
                                'Zeta'::VARCHAR
                            ),
                            (
                                10::INTEGER,
                                'israel'::VARCHAR,
                                'Holiday'::VARCHAR,
                                'Zeta'::VARCHAR,
                                'zeta'::VARCHAR,
                                2::INTEGER,
                                'Zeta'::VARCHAR,
                                'זטא'::VARCHAR,
                                'Zeta'::VARCHAR
                            ),
                            (
                                {event_day}::INTEGER,
                                'diaspora'::VARCHAR,
                                'Fast'::VARCHAR,
                                'Alpha'::VARCHAR,
                                'alpha'::VARCHAR,
                                1::INTEGER,
                                'Alpha'::VARCHAR,
                                'אלפא'::VARCHAR,
                                'Alpha'::VARCHAR
                            )
                    ) AS rows(
                        absolute_day,
                        schedule,
                        event_class,
                        event_description,
                        event_basename,
                        event_flags,
                        title_en,
                        title_he,
                        title_ashkenazi
                    )
                    ORDER BY absolute_day, schedule, event_class
                )
                TO {sql_literal(event_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

        files = {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (day_path, schedule_path, event_path)
        }
        partition_manifest = partition_root / "manifest.json"
        write_json_exclusive(partition_manifest, {"files": files})
        root_manifest = corpus_root / "manifest.json"
        write_json_exclusive(
            root_manifest,
            {
                "corpus_version": "v1",
                "status": "complete-immutable",
                "partitions": [
                    {
                        "block": "0001-0001",
                        "manifest_sha256": sha256(partition_manifest),
                        "files": files,
                    }
                ],
            },
        )
        write_json_exclusive(
            corpus_root / "provenance.json",
            {"content_manifest_sha256": sha256(root_manifest)},
        )
        return corpus_root

    def test_materializes_exact_keys_nulls_and_relationships(self):
        with tempfile.TemporaryDirectory(prefix="torah-data-powerbi-") as temp:
            temp_root = Path(temp)
            corpus_root = self._write_fixture(temp_root)
            output_root = temp_root / "powerbi-v1"
            manifest_path = materialize(corpus_root, output_root)
            manifest = load_json(manifest_path)

            self.assertFalse(manifest["official_corpus_v1_baseline_verified"])
            self.assertEqual(
                manifest["validation"]["hebrew_day_schedule"]["rows"], 4
            )
            self.assertEqual(
                manifest["validation"]["hebrew_day_schedule"][
                    "rows_by_schedule"
                ],
                {"diaspora": 2, "israel": 2},
            )
            self.assertEqual(
                manifest["validation"]["hebrew_day_schedule"][
                    "unsupported_tachanun_rows"
                ],
                2,
            )
            self.assertEqual(
                manifest["validation"]["hebcal_event_definition"]["rows"], 2
            )
            self.assertEqual(
                manifest["validation"]["hebcal_event_occurrence"][
                    "rows_by_schedule"
                ],
                {"diaspora": 2, "israel": 1},
            )

            with duckdb.connect() as connection:
                schedule_rows = connection.execute(
                    """
                    SELECT *
                    FROM read_parquet(?)
                    ORDER BY absolute_day, schedule_key
                    """,
                    [str(output_root / "hebrew_day_schedule.parquet")],
                ).fetchall()
                definitions = connection.execute(
                    """
                    SELECT event_definition_key, event_class
                    FROM read_parquet(?)
                    ORDER BY event_definition_key
                    """,
                    [str(output_root / "hebcal_event_definition.parquet")],
                ).fetchall()
                occurrences = connection.execute(
                    """
                    SELECT *
                    FROM read_parquet(?)
                    ORDER BY absolute_day, schedule_key, event_definition_key
                    """,
                    [str(output_root / "hebcal_event_occurrence.parquet")],
                ).fetchall()

            self.assertEqual(definitions, [(1, "Fast"), (2, "Holiday")])
            self.assertEqual(
                [(row[0], row[1]) for row in schedule_rows],
                [(10, 0), (10, 1), (11, 0), (11, 1)],
            )
            self.assertEqual(schedule_rows[0][3:6], (True, True, True))
            self.assertEqual(schedule_rows[2][3:6], (None, None, None))
            self.assertEqual(
                occurrences,
                [(10, 0, 2), (10, 1, 2), (11, 0, 1)],
            )

    def test_is_deterministic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="torah-data-powerbi-") as temp:
            temp_root = Path(temp)
            corpus_root = self._write_fixture(temp_root)
            output_a = temp_root / "powerbi-a"
            output_b = temp_root / "powerbi-b"
            materialize(corpus_root, output_a)
            materialize(corpus_root, output_b)

            deterministic_files = (*OUTPUT_TABLE_FILES, "manifest.json")
            self.assertEqual(
                {name: sha256(output_a / name) for name in deterministic_files},
                {name: sha256(output_b / name) for name in deterministic_files},
            )
            with self.assertRaises(FileExistsError):
                materialize(corpus_root, output_a)

    def test_rejects_an_orphan_without_landing_output(self):
        with tempfile.TemporaryDirectory(prefix="torah-data-powerbi-") as temp:
            temp_root = Path(temp)
            corpus_root = self._write_fixture(temp_root, orphan_event=True)
            output_root = temp_root / "powerbi-v1"
            with self.assertRaises(RuntimeError):
                materialize(corpus_root, output_root)
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
