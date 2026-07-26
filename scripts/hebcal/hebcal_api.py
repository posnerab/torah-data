#!/usr/bin/env python3
"""Small, dependency-free helpers for the Hebcal REST APIs."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://www.hebcal.com"
USER_AGENT = "posnerab-torah-data/1.0 (+https://github.com/posnerab/torah-data)"
MAX_RANGE_DAYS = 180
SAFE_ENDPOINT = re.compile(r"^/[A-Za-z0-9/_-]+$")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def format_date(value: date) -> str:
    return value.isoformat()


def parse_parameter(value: str) -> tuple[str, str]:
    key, separator, parameter_value = value.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError("parameters must use KEY=VALUE")
    return key, parameter_value


def date_chunks(start: date, end: date, size: int = MAX_RANGE_DAYS) -> Iterable[tuple[date, date]]:
    """Yield inclusive ranges containing no more than ``size`` dates."""
    if end < start:
        raise ValueError("end must not be before start")
    if size < 1:
        raise ValueError("size must be positive")
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=size - 1), end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def _merge_unique_items(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for response in responses:
        for item in response.get("items", []):
            identity = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if identity not in seen:
                seen.add(identity)
                items.append(item)
    items.sort(
        key=lambda item: (
            str(item.get("date", "")),
            str(item.get("category", "")),
            json.dumps(item.get("name", ""), ensure_ascii=False, sort_keys=True),
            str(item.get("title", "")),
        )
    )
    return items


@dataclass
class HebcalClient:
    timeout_seconds: float = 30.0
    max_attempts: int = 4
    minimum_delay_seconds: float = 0.12

    def request(self, endpoint: str, parameters: Iterable[tuple[str, str]]) -> dict[str, Any]:
        """Exercise any JSON GET endpoint exposed by Hebcal."""
        if not SAFE_ENDPOINT.fullmatch(endpoint) or ".." in endpoint:
            raise ValueError("endpoint must be a simple Hebcal path such as /converter")
        return self._get(endpoint, dict(parameters))

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode([(key, value) for key, value in params.items() if value is not None])
        request = Request(
            f"{BASE_URL}{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                time.sleep(self.minimum_delay_seconds * (2 ** (attempt - 2)))
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError(f"Expected a JSON object from {path}")
                time.sleep(self.minimum_delay_seconds)
                return payload
            except HTTPError as error:
                if error.code != 429 and error.code < 500:
                    raise
                if attempt == self.max_attempts:
                    raise
                retry_after = error.headers.get("Retry-After")
                if retry_after:
                    time.sleep(float(retry_after))
            except (TimeoutError, URLError):
                if attempt == self.max_attempts:
                    raise
        raise RuntimeError("unreachable")

    def calendar(
        self,
        *,
        year: int | None = None,
        start: date | None = None,
        end: date | None = None,
        language: str = "a",
        include_candles: bool = False,
        location: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if year is None and (start is None or end is None):
            raise ValueError("calendar requires either year or start and end")
        if year is not None and (start is not None or end is not None):
            raise ValueError("calendar accepts year or start/end, not both")
        params: dict[str, Any] = {
            "v": 1,
            "cfg": "json",
            "maj": "on",
            "min": "on",
            "nx": "on",
            "ss": "on",
            "mf": "on",
            "o": "on",
            "s": "on",
            "d": "on",
            "lg": language,
            "year": year,
            "start": format_date(start) if start else None,
            "end": format_date(end) if end else None,
            "c": "on" if include_candles else None,
        }
        if location:
            params.update(location)
        return self._get("/hebcal", params)

    def leyning(self, *, start: date, end: date, israel: bool = False) -> dict[str, Any]:
        responses = [
            self._get(
                "/leyning",
                {
                    "cfg": "json",
                    "start": format_date(chunk_start),
                    "end": format_date(chunk_end),
                    "i": "on" if israel else "off",
                    "triennial": "off",
                },
            )
            for chunk_start, chunk_end in date_chunks(start, end)
        ]
        return {
            "source": "Hebcal Leyning API",
            "location": "Israel" if israel else "Diaspora",
            "range": {"start": format_date(start), "end": format_date(end)},
            "items": _merge_unique_items(responses),
        }

    def zmanim(
        self,
        *,
        start: date,
        end: date,
        location: dict[str, Any],
        seconds: bool = True,
    ) -> dict[str, Any]:
        responses = [
            self._get(
                "/zmanim",
                {
                    "cfg": "json",
                    "start": format_date(chunk_start),
                    "end": format_date(chunk_end),
                    "sec": 1 if seconds else None,
                    **location,
                },
            )
            for chunk_start, chunk_end in date_chunks(start, end)
        ]
        times: dict[str, dict[str, str]] = {}
        for response in responses:
            for zman, values in response.get("times", {}).items():
                if isinstance(values, dict):
                    times.setdefault(zman, {}).update(values)
                    continue
                response_date = response.get("date")
                if response_date:
                    times.setdefault(zman, {})[response_date] = values
        return {
            "source": "Hebcal Zmanim API",
            "range": {"start": format_date(start), "end": format_date(end)},
            "location": responses[0].get("location", {}) if responses else {},
            "times": {name: dict(sorted(values.items())) for name, values in sorted(times.items())},
        }


def write_json(payload: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")


def _location_from_args(args: argparse.Namespace) -> dict[str, Any]:
    candidates = [
        ("zip", args.zip),
        ("geonameid", args.geonameid),
    ]
    supplied = [(key, value) for key, value in candidates if value]
    if args.latitude is not None or args.longitude is not None:
        if args.latitude is None or args.longitude is None:
            raise ValueError("latitude and longitude must be supplied together")
        supplied.append(("pos", f"{args.latitude},{args.longitude}"))
    if len(supplied) != 1:
        raise ValueError("choose exactly one location: --zip, --geonameid, or --latitude/--longitude")
    key, value = supplied[0]
    if key == "pos":
        latitude, longitude = value.split(",", 1)
        return {"geo": "pos", "latitude": latitude, "longitude": longitude}
    return {key: value}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    calendar_parser = subparsers.add_parser("calendar", help="Fetch Jewish calendar events")
    date_group = calendar_parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--year", type=int)
    date_group.add_argument("--start", type=parse_date)
    calendar_parser.add_argument("--end", type=parse_date)
    calendar_parser.add_argument("--language", default="a")
    calendar_parser.add_argument("--include-candles", action="store_true")
    _add_location_arguments(calendar_parser)
    calendar_parser.add_argument("--output", type=Path)

    leyning_parser = subparsers.add_parser("leyning", help="Fetch Torah-reading data")
    leyning_parser.add_argument("--start", type=parse_date, required=True)
    leyning_parser.add_argument("--end", type=parse_date, required=True)
    leyning_parser.add_argument("--israel", action="store_true")
    leyning_parser.add_argument("--output", type=Path)

    zmanim_parser = subparsers.add_parser("zmanim", help="Fetch halachic times")
    zmanim_parser.add_argument("--start", type=parse_date, required=True)
    zmanim_parser.add_argument("--end", type=parse_date, required=True)
    zmanim_parser.add_argument("--minute-precision", action="store_true")
    _add_location_arguments(zmanim_parser)
    zmanim_parser.add_argument("--output", type=Path)

    raw_parser = subparsers.add_parser(
        "request",
        help="Exercise another Hebcal JSON GET endpoint",
    )
    raw_parser.add_argument("--endpoint", required=True)
    raw_parser.add_argument(
        "--param",
        type=parse_parameter,
        action="append",
        default=[],
        metavar="KEY=VALUE",
    )
    raw_parser.add_argument("--output", type=Path)
    return parser


def _add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--zip")
    parser.add_argument("--geonameid", type=int)
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)


def main() -> int:
    args = build_parser().parse_args()
    client = HebcalClient(timeout_seconds=args.timeout)
    if args.command == "calendar":
        if args.start and not args.end:
            raise SystemExit("--end is required with --start")
        location = None
        if args.include_candles:
            location = _location_from_args(args)
        payload = client.calendar(
            year=args.year,
            start=args.start,
            end=args.end,
            language=args.language,
            include_candles=args.include_candles,
            location=location,
        )
    elif args.command == "leyning":
        payload = client.leyning(start=args.start, end=args.end, israel=args.israel)
    elif args.command == "zmanim":
        payload = client.zmanim(
            start=args.start,
            end=args.end,
            location=_location_from_args(args),
            seconds=not args.minute_precision,
        )
    else:
        payload = client.request(args.endpoint, args.param)
    write_json(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
