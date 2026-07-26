#!/usr/bin/env python3
"""Populate every missing corpus-v1 block and finalize the immutable corpus."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from build_corpus import build_partition, load_json, sha256
from finalize_corpus import CONTRACT_PATH, expected_blocks, finalize


def verify_existing_partition(path: Path, start: int, end: int) -> None:
    manifest_path = path / "manifest.json"
    manifest = load_json(manifest_path)
    if (
        manifest["start_year"] != start
        or manifest["end_year"] != end
        or manifest["corpus_version"] != "v1"
    ):
        raise RuntimeError(f"{path} has the wrong immutable manifest")
    for file_name, expected in manifest["files"].items():
        file_path = path / file_name
        if not file_path.exists() or sha256(file_path) != expected["sha256"]:
            raise RuntimeError(f"{file_path} failed immutable checksum verification")


def populate(output_root: Path, workers: int) -> Path:
    if workers < 1:
        raise ValueError("workers must be positive")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    final_manifest = output_root / "manifest.json"
    if final_manifest.exists():
        raise FileExistsError(
            f"{final_manifest} already exists; corpus-v1 is already finalized"
        )

    contract = load_json(CONTRACT_PATH)
    missing: list[tuple[int, int]] = []
    for start, end, name in expected_blocks(contract):
        partition = output_root / name
        if partition.exists():
            verify_existing_partition(partition, start, end)
            print(f"verified {name}")
        else:
            missing.append((start, end))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(build_partition, start, end, output_root): (start, end)
            for start, end in missing
        }
        for future in as_completed(futures):
            start, end = futures[future]
            partition = future.result()
            print(f"built {partition.name} ({start}-{end})")

    return finalize(output_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(populate(args.output_root, args.workers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
