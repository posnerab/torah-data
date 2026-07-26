import json
import tempfile
import unittest
from pathlib import Path

import duckdb

from build_corpus import build_partition
from finalize_corpus import expected_blocks, finalize
from build_corpus import load_json


class CorpusBuildTests(unittest.TestCase):
    def test_contract_has_exactly_sixty_contiguous_blocks(self):
        contract = load_json(Path(__file__).with_name("corpus-v1.json"))
        blocks = expected_blocks(contract)
        self.assertEqual(len(blocks), 60)
        self.assertEqual(blocks[0], (1, 100, "block=0001-0100"))
        self.assertEqual(blocks[-1], (5901, 6000, "block=5901-6000"))

    def test_finalizer_refuses_an_incomplete_corpus(self):
        with tempfile.TemporaryDirectory(prefix="torah-data-hebcal-") as temp:
            with self.assertRaises(RuntimeError):
                finalize(Path(temp))

    def test_builds_and_then_protects_an_immutable_partition(self):
        with tempfile.TemporaryDirectory(prefix="torah-data-hebcal-") as temp:
            output_root = Path(temp)
            partition = build_partition(1, 1, output_root)
            manifest = json.loads(
                (partition / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["corpus_version"], "v1")
            self.assertEqual(manifest["validation"]["core_day"]["rows"], 355)
            self.assertEqual(
                manifest["validation"]["core_day_schedule"]["rows"],
                710,
            )
            self.assertEqual(
                manifest["validation"]["core_day"]["first_absolute_day"],
                -1373427,
            )
            self.assertGreater(
                manifest["validation"]["core_parasha_occurrence"]["rows"],
                0,
            )
            self.assertGreater(
                manifest["validation"]["core_leyning_occurrence"]["rows"],
                0,
            )
            with duckdb.connect() as connection:
                rows = connection.execute(
                    "SELECT count(*) FROM read_parquet(?)",
                    [str(partition / "core_day.parquet")],
                ).fetchone()[0]
            self.assertEqual(rows, 355)
            with self.assertRaises(FileExistsError):
                build_partition(1, 1, output_root)


if __name__ == "__main__":
    unittest.main()
