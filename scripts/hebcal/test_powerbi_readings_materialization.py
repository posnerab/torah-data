import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from materialize_powerbi_readings import (
    OUTPUT_TABLE_FILES,
    load_json,
    materialize,
    sha256,
    sql_literal,
    write_json_exclusive,
)


def compact_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def localized_payload(
    *,
    locale: str,
    holiday: bool = False,
    locale_mismatch: bool = False,
    unknown_root: bool = False,
    unknown_path: bool = False,
):
    text = {
        "en": {
            "book": "Genesis",
            "begin": "1:1",
            "end": "1:3",
            "reason": "First aliyah",
            "note": "Only note",
            "summary": "Alpha summary",
        },
        "he": {
            "book": "בראשית",
            "begin": "א:א",
            "end": "א:ג",
            "reason": "עלייה ראשונה",
            "note": "הערה יחידה",
            "summary": "סיכום אלפא",
        },
        "ashkenazi": {
            "book": "Bereishis",
            "begin": "1:1",
            "end": "1:3",
            "reason": "Ersht aliyah",
            "note": "Eyntsike note",
            "summary": "Alpha simkhe",
        },
    }[locale]
    if holiday:
        payload = {
            "name": {"en": "Holiday", "he": "חג"},
            "type": "holiday",
            "parsha": ["Beta"],
            "parshaNum": 2,
            "summaryParts": [
                {
                    "k": text["book"],
                    "b": text["begin"],
                    "e": text["end"],
                },
                {
                    "k": text["book"],
                    "b": "2:1" if locale != "he" else "ב:א",
                    "e": "2:2" if locale != "he" else "ב:ב",
                },
            ],
        }
    else:
        payload = {
            "name": {"en": "Alpha", "he": "אלפא"},
            "type": "shabbat",
            "summary": text["summary"],
            "parsha": ["Alpha"],
            "parshaNum": 1,
            "fullkriyah": {
                "1": {
                    "k": text["book"],
                    "b": text["begin"],
                    "e": text["end"],
                    "v": 3,
                    "p": 1,
                    "reason": text["reason"],
                },
                "M": {
                    "k": text["book"],
                    "b": "1:4" if locale != "he" else "א:ד",
                    "e": "1:5" if locale != "he" else "א:ה",
                    "v": 2,
                    "p": 1,
                },
            },
            "haft": [
                {
                    "k": "Isaiah" if locale == "en" else text["book"],
                    "b": text["begin"],
                    "e": text["end"],
                    "v": 3,
                    "reason": text["reason"],
                    "note": text["note"],
                },
                {
                    "k": "Isaiah" if locale == "en" else text["book"],
                    "b": "2:1" if locale != "he" else "ב:א",
                    "e": "2:2" if locale != "he" else "ב:ב",
                    "v": 2,
                    "reason": text["reason"],
                },
            ],
        }
    if locale_mismatch and locale == "he" and not holiday:
        payload["haft"] = payload["haft"][:1]
    if unknown_root:
        payload["mysteryPassage"] = {"k": "Unknown", "b": "1", "e": "2"}
    if unknown_path and not holiday:
        payload["fullkriyah"]["1"]["unexpected"] = "value"
    return payload


class PowerBiReadingsMaterializationTests(unittest.TestCase):
    def _write_fixture(
        self,
        root: Path,
        *,
        orphan_parasha: bool = False,
        locale_mismatch: bool = False,
        unknown_root: bool = False,
        unknown_path: bool = False,
    ) -> Path:
        corpus_root = root / "corpus-v1"
        partition_root = corpus_root / "block=0001-0001"
        partition_root.mkdir(parents=True)

        day_path = partition_root / "core_day.parquet"
        schedule_path = partition_root / "core_day_schedule.parquet"
        parasha_path = partition_root / "core_parasha_occurrence.parquet"
        leyning_path = partition_root / "core_leyning_occurrence.parquet"

        alpha_payloads = {
            locale: compact_json(
                localized_payload(
                    locale=locale,
                    locale_mismatch=locale_mismatch,
                    unknown_root=unknown_root,
                    unknown_path=unknown_path,
                )
            )
            for locale in ("en", "he", "ashkenazi")
        }
        holiday_payloads = {
            locale: compact_json(
                localized_payload(locale=locale, holiday=True)
            )
            for locale in ("en", "he", "ashkenazi")
        }
        alpha_hash = hashlib.sha256(
            alpha_payloads["en"].encode("utf-8")
        ).hexdigest()
        holiday_hash = hashlib.sha256(
            holiday_payloads["en"].encode("utf-8")
        ).hexdigest()

        with duckdb.connect() as connection:
            connection.execute(
                """
                CREATE TABLE fixture_day (
                    absolute_day INTEGER,
                    hebrew_year INTEGER,
                    weekday_sunday_0 SMALLINT
                )
                """
            )
            connection.executemany(
                "INSERT INTO fixture_day VALUES (?, ?, ?)",
                [(10, 1, 6), (11, 1, 6)],
            )
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM fixture_day ORDER BY absolute_day
                )
                TO {sql_literal(day_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

            connection.execute(
                """
                CREATE TABLE fixture_schedule (
                    absolute_day INTEGER,
                    schedule VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO fixture_schedule VALUES (?, ?)",
                [
                    (10, "diaspora"),
                    (10, "israel"),
                    (11, "diaspora"),
                    (11, "israel"),
                ],
            )
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM fixture_schedule
                    ORDER BY absolute_day, schedule
                )
                TO {sql_literal(schedule_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

            connection.execute(
                """
                CREATE TABLE fixture_parasha (
                    occurrence_id VARCHAR,
                    hebrew_year INTEGER,
                    schedule VARCHAR,
                    absolute_day INTEGER,
                    parasha VARCHAR[],
                    is_combined BOOLEAN,
                    title_en VARCHAR,
                    title_he VARCHAR,
                    title_ashkenazi VARCHAR,
                    basename VARCHAR,
                    raw_event_json VARCHAR
                )
                """
            )
            parasha_day = 99 if orphan_parasha else 11
            connection.executemany(
                "INSERT INTO fixture_parasha VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "p-10-d",
                        1,
                        "diaspora",
                        10,
                        ["Alpha"],
                        False,
                        "Alpha",
                        "אלפא",
                        "Alpha",
                        "alpha",
                        '{"title":"Alpha"}',
                    ),
                    (
                        "p-10-i",
                        1,
                        "israel",
                        10,
                        ["Alpha"],
                        False,
                        "Alpha",
                        "אלפא",
                        "Alpha",
                        "alpha",
                        '{"title":"Alpha"}',
                    ),
                    (
                        "p-11-d",
                        1,
                        "diaspora",
                        parasha_day,
                        ["Alpha", "Beta"],
                        True,
                        "Alpha-Beta",
                        "אלפא-בטא",
                        "Alpha-Beisa",
                        "alpha-beta",
                        '{"title":"Alpha-Beta"}',
                    ),
                ],
            )
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM fixture_parasha
                    ORDER BY absolute_day, schedule
                )
                TO {sql_literal(parasha_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

            connection.execute(
                """
                CREATE TABLE fixture_leyning (
                    occurrence_id VARCHAR,
                    hebrew_year INTEGER,
                    schedule VARCHAR,
                    absolute_day INTEGER,
                    reading_index SMALLINT,
                    reading_type VARCHAR,
                    name_en VARCHAR,
                    name_he VARCHAR,
                    summary VARCHAR,
                    summary_he VARCHAR,
                    summary_ashkenazi VARCHAR,
                    parasha_json VARCHAR,
                    parasha_num_json VARCHAR,
                    raw_reading_json VARCHAR,
                    raw_reading_json_he VARCHAR,
                    raw_reading_json_ashkenazi VARCHAR,
                    source_payload_sha256 VARCHAR
                )
                """
            )
            alpha_row = (
                "shabbat",
                "Alpha",
                "אלפא",
                "Alpha summary",
                "סיכום אלפא",
                "Alpha simkhe",
                '["Alpha"]',
                "1",
                alpha_payloads["en"],
                alpha_payloads["he"],
                alpha_payloads["ashkenazi"],
                alpha_hash,
            )
            holiday_row = (
                "holiday",
                "Holiday",
                "חג",
                None,
                None,
                None,
                '["Beta"]',
                "2",
                holiday_payloads["en"],
                holiday_payloads["he"],
                holiday_payloads["ashkenazi"],
                holiday_hash,
            )
            connection.executemany(
                """
                INSERT INTO fixture_leyning
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("l-10-d", 1, "diaspora", 10, 0, *alpha_row),
                    ("l-10-i", 1, "israel", 10, 0, *alpha_row),
                    ("l-11-d", 1, "diaspora", 11, 0, *holiday_row),
                    ("l-11-i", 1, "israel", 11, 0, *holiday_row),
                ],
            )
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM fixture_leyning
                    ORDER BY absolute_day, schedule, reading_index
                )
                TO {sql_literal(leyning_path)}
                (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )

        files = {
            path.name: {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (
                day_path,
                schedule_path,
                parasha_path,
                leyning_path,
            )
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

    def test_materializes_exact_schema_keys_and_localized_segments(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root)
            output_root = root / "powerbi-readings-v1"
            manifest = load_json(materialize(corpus_root, output_root))

            self.assertFalse(manifest["official_corpus_v1_baseline_verified"])
            self.assertEqual(
                set(manifest["files"]),
                set(OUTPUT_TABLE_FILES),
            )
            self.assertEqual(
                manifest["validation"]["parasha_definition"]["rows"], 2
            )
            self.assertEqual(
                manifest["validation"]["parasha_definition_member"]["rows"], 3
            )
            self.assertEqual(
                manifest["validation"]["parasha_occurrence"]["rows"], 3
            )
            self.assertEqual(
                manifest["validation"]["leyning_reading_definition"]["rows"],
                2,
            )
            self.assertEqual(
                manifest["validation"]["leyning_segment_definition"][
                    "rows_by_kind"
                ],
                {"fullkriyah": 2, "haft": 2, "summaryParts": 2},
            )

            with duckdb.connect() as connection:
                definition_columns = [
                    row[0]
                    for row in connection.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?)",
                        [
                            str(
                                output_root
                                / "leyning_reading_definition.parquet"
                            )
                        ],
                    ).fetchall()
                ]
                segment_columns = [
                    row[0]
                    for row in connection.execute(
                        "DESCRIBE SELECT * FROM read_parquet(?)",
                        [
                            str(
                                output_root
                                / "leyning_segment_definition.parquet"
                            )
                        ],
                    ).fetchall()
                ]
                segments = connection.execute(
                    """
                    SELECT
                        segment_kind,
                        segment_label,
                        segment_index,
                        book_en,
                        book_he,
                        begin_ref_en,
                        begin_ref_he,
                        reason_en,
                        reason_he,
                        note_en,
                        note_he
                    FROM read_parquet(?)
                    ORDER BY reading_definition_key, segment_kind, segment_index
                    """,
                    [
                        str(
                            output_root
                            / "leyning_segment_definition.parquet"
                        )
                    ],
                ).fetchall()

            self.assertEqual(
                definition_columns,
                [
                    "reading_definition_key",
                    "source_payload_sha256",
                    "reading_type",
                    "name_en",
                    "name_he",
                    "summary",
                    "summary_he",
                    "summary_ashkenazi",
                ],
            )
            self.assertEqual(len(segment_columns), 21)
            self.assertNotIn("raw_reading_json", definition_columns)
            self.assertIn(
                (
                    "haft",
                    "1",
                    1,
                    "Isaiah",
                    "בראשית",
                    "1:1",
                    "א:א",
                    "First aliyah",
                    "עלייה ראשונה",
                    "Only note",
                    "הערה יחידה",
                ),
                segments,
            )
            self.assertIn(("haft", "2", 2), [row[:3] for row in segments])
            self.assertIn(
                ("fullkriyah", "M", 2),
                [row[:3] for row in segments],
            )

    def test_is_deterministic_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root)
            output_a = root / "readings-a"
            output_b = root / "readings-b"
            materialize(corpus_root, output_a)
            materialize(corpus_root, output_b)

            for file_name in (*OUTPUT_TABLE_FILES, "manifest.json"):
                self.assertEqual(
                    sha256(output_a / file_name),
                    sha256(output_b / file_name),
                    file_name,
                )
            with self.assertRaises(FileExistsError):
                materialize(corpus_root, output_a)

    def test_orphan_fails_without_landing_output(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root, orphan_parasha=True)
            output_root = root / "failed-output"
            with self.assertRaisesRegex(
                RuntimeError, "source reading relationship integrity failed"
            ):
                materialize(corpus_root, output_root)
            self.assertFalse(output_root.exists())

    def test_unknown_json_root_fails_without_landing_output(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root, unknown_root=True)
            output_root = root / "failed-output"
            with self.assertRaisesRegex(RuntimeError, "unexpected JSON root"):
                materialize(corpus_root, output_root)
            self.assertFalse(output_root.exists())

    def test_locale_structure_mismatch_fails_without_landing_output(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root, locale_mismatch=True)
            output_root = root / "failed-output"
            with self.assertRaisesRegex(
                RuntimeError, "locale JSON structures differ"
            ):
                materialize(corpus_root, output_root)
            self.assertFalse(output_root.exists())

    def test_unknown_json_path_fails_without_landing_output(self):
        with tempfile.TemporaryDirectory(
            prefix="torah-data-powerbi-readings-"
        ) as temp:
            root = Path(temp)
            corpus_root = self._write_fixture(root, unknown_path=True)
            output_root = root / "failed-output"
            with self.assertRaisesRegex(
                RuntimeError, "unexpected passage fields"
            ):
                materialize(corpus_root, output_root)
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
