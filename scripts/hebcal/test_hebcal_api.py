import unittest
from datetime import date

from hebcal_api import HebcalClient, date_chunks, parse_parameter


class FakeClient(HebcalClient):
    def __init__(self, responses):
        super().__init__(minimum_delay_seconds=0)
        self.responses = iter(responses)
        self.calls = []

    def _get(self, path, params):
        self.calls.append((path, params))
        return next(self.responses)


class HebcalApiTests(unittest.TestCase):
    def test_generic_request_validates_endpoint_and_parameters(self):
        client = FakeClient([{"gy": 2026, "hm": "Av", "hd": 11}])
        result = client.request(
            "/converter",
            [parse_parameter("cfg=json"), parse_parameter("g2h=1")],
        )
        self.assertEqual(result["hm"], "Av")
        self.assertEqual(
            client.calls,
            [("/converter", {"cfg": "json", "g2h": "1"})],
        )
        with self.assertRaises(ValueError):
            client.request("https://example.com", [])

    def test_date_chunks_are_inclusive_and_capped_at_180_days(self):
        chunks = list(date_chunks(date(2026, 1, 1), date(2026, 12, 31)))
        self.assertEqual(
            chunks,
            [
                (date(2026, 1, 1), date(2026, 6, 29)),
                (date(2026, 6, 30), date(2026, 12, 26)),
                (date(2026, 12, 27), date(2026, 12, 31)),
            ],
        )

    def test_leyning_combines_chunks_and_removes_duplicate_items(self):
        shared = {"date": "2026-06-29", "name": {"en": "Balak"}}
        client = FakeClient(
            [
                {"items": [{"date": "2026-01-01", "name": {"en": "Vayechi"}}, shared]},
                {"items": [shared, {"date": "2026-06-30", "name": {"en": "Pinchas"}}]},
            ]
        )
        result = client.leyning(start=date(2026, 1, 1), end=date(2026, 6, 30))
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(result["items"]), 3)

    def test_zmanim_merges_time_records_from_multiple_chunks(self):
        client = FakeClient(
            [
                {
                    "location": {"city": "Milwaukee"},
                    "times": {"sunrise": {"2026-01-01": "2026-01-01T07:23:00-06:00"}},
                },
                {
                    "location": {"city": "Milwaukee"},
                    "times": {"sunrise": {"2026-06-30": "2026-06-30T05:16:00-05:00"}},
                },
            ]
        )
        result = client.zmanim(
            start=date(2026, 1, 1),
            end=date(2026, 6, 30),
            location={"zip": "53216"},
        )
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(result["times"]["sunrise"]), 2)
        self.assertEqual(result["location"]["city"], "Milwaukee")

    def test_zmanim_normalizes_single_day_scalar_times(self):
        client = FakeClient(
            [
                {
                    "date": "2026-07-26",
                    "location": {"city": "Milwaukee"},
                    "times": {"sunrise": "2026-07-26T05:36:31-05:00"},
                }
            ]
        )
        result = client.zmanim(
            start=date(2026, 7, 26),
            end=date(2026, 7, 26),
            location={"zip": "53216"},
        )
        self.assertEqual(
            result["times"]["sunrise"],
            {"2026-07-26": "2026-07-26T05:36:31-05:00"},
        )


if __name__ == "__main__":
    unittest.main()
