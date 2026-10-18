"""Offline tests only: no credentials, browser sessions, or Garmin requests."""

import argparse
import json
import os
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

import export_golf as exporter


class FakeGolf:
    unit_system = "statute"

    def __init__(self, cards=None):
        self.cards = cards if cards is not None else [{"scorecardId": 123, "courseName": "Test course"}]
        self.calls = []

    def get_golf_user_stats(self):
        self.calls.append("stats")
        return {"handicap": 14}

    def get_golf_club_stats(self):
        self.calls.append("clubs")
        return {"clubs": [{"name": "7 iron", "averageDistance": 145}]}

    def get_golf_summary(self, start, limit):
        self.calls.append(("summary", start, limit))
        return self.cards

    def get_golf_scorecard(self, card_id):
        self.calls.append(("scorecard", card_id))
        return {"scorecardId": card_id, "strokes": 88}

    def get_golf_shot_data(self, card_id):
        self.calls.append(("shots", card_id))
        return {"holes": []}

    def connectapi(self, path):
        self.calls.append(("catalog", path))
        return [{"id": 14, "name": "6 iron"}]


def collect(api, **kwargs):
    return exporter.collect_golf(api, progress=lambda _: None, delay_seconds=0, **kwargs)


class ScorecardTests(unittest.TestCase):
    def test_known_summary_shapes(self):
        cards = [{"scorecardId": 123}]
        for shape in (cards, {"scorecardList": cards}, {"items": cards}, {"scorecards": cards}, {"scorecardSummaries": cards}):
            with self.subTest(shape=shape):
                self.assertEqual(exporter.scorecard_list(shape), cards)
        self.assertEqual(exporter.scorecard_list(cards[0]), cards)

    def test_empty_summary_shapes(self):
        for shape in (None, [], {}, {"items": []}, {"scorecardList": None}):
            self.assertEqual(exporter.scorecard_list(shape), [])

    def test_unrecognized_summary_rejected(self):
        for shape in ("unexpected", [123], {"unrelated": []}, {"items": {"id": 123}}):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                exporter.scorecard_list(shape)

    def test_numeric_ids_only(self):
        self.assertEqual(exporter.scorecard_id({"scorecardId": "00123"}), "123")
        self.assertEqual(exporter.scorecard_id({"id": 456}), "456")
        for value in (True, False, 0, -1, "../123", "123?x=1", "1.0", "", None, 1.5):
            with self.subTest(value=value):
                self.assertIsNone(exporter.scorecard_id({"scorecardId": value}))


class CollectionTests(unittest.TestCase):
    def test_installed_library_methods_use_only_golf_read_endpoints(self):
        api = exporter.Garmin(retry_attempts=0)
        api.client.connectapi = Mock(side_effect=[
            {"handicap": 14}, {"clubs": []}, [{"scorecardId": 123}],
            {"scorecardId": 123}, {"holes": []},
        ])
        # Any unexpected transport request must fail offline, not reach Garmin.
        api.client.request = Mock(side_effect=AssertionError("No live requests in tests"))
        result = collect(api, include_shots=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(api.client.connectapi.call_count, 5)
        for call in api.client.connectapi.call_args_list:
            self.assertTrue(call.args[0].startswith("/gcs-golfcommunity/api/v2/"))
        api.client.request.assert_not_called()

    def test_only_golf_reads_and_no_shots_by_default(self):
        api = FakeGolf()
        result = collect(api)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["successful_requests"], 4)
        self.assertEqual(api.calls, ["stats", "clubs", ("summary", 0, 20), ("scorecard", "123")])
        self.assertNotIn("shots", result["golf"]["scorecards"][0])

    def test_round_count_is_bounded_and_duplicates_are_not_downloaded_twice(self):
        api = FakeGolf([{"id": 1}, {"id": 1}, {"id": 2}, {"id": 3}])
        result = collect(api, rounds=3)
        self.assertEqual(len(result["golf"]["scorecard_summaries"]), 3)
        self.assertEqual([x["scorecard_id"] for x in result["golf"]["scorecards"]], ["1", "2"])
        self.assertNotIn(("scorecard", "3"), api.calls)

    def test_shots_require_explicit_opt_in(self):
        api = FakeGolf()
        result = collect(api, include_shots=True)
        self.assertIn(("shots", "123"), api.calls)
        self.assertEqual(result["golf"]["scorecards"][0]["shots"], {"holes": []})
        self.assertNotIn("club_types", result["golf"])

    def test_shot_exports_do_not_depend_on_a_remote_club_type_catalog(self):
        api = FakeGolf()
        api.connectapi = Mock(side_effect=GarminConnectNotFoundError("unavailable"))
        result = collect(api, rounds=3, include_shots=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["golf"]["scorecards"][0]["shots"], {"holes": []})
        api.connectapi.assert_not_called()

    def test_missing_ids_are_reported_without_guessing(self):
        api = FakeGolf([{"courseName": "Test"}, {"id": "invalid"}])
        result = collect(api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual(result["golf"]["scorecards"], [])

    def test_rate_limit_or_auth_failure_stops_further_requests(self):
        for error in (GarminConnectTooManyRequestsError, GarminConnectAuthenticationError):
            with self.subTest(error=error):
                api = FakeGolf()
                api.get_golf_club_stats = Mock(side_effect=error("DO-NOT-EXPORT-THIS"))
                result = collect(api)
                self.assertTrue(result["stopped_early"])
                self.assertEqual(result["successful_requests"], 1)
                self.assertEqual(api.calls, ["stats"])
                self.assertNotIn("DO-NOT-EXPORT-THIS", json.dumps(result))

    def test_mid_round_rate_limit_preserves_partial_results(self):
        api = FakeGolf()
        api.get_golf_scorecard = Mock(side_effect=GarminConnectTooManyRequestsError("private"))
        result = collect(api, include_shots=True)
        self.assertTrue(result["stopped_early"])
        self.assertIsNone(result["golf"]["scorecards"][0]["detail"])
        self.assertNotIn(("shots", "123"), api.calls)

    def test_unavailable_sections_do_not_block_other_golf_reads(self):
        for error in (GarminConnectNotFoundError, GarminConnectConnectionError):
            api = FakeGolf()
            api.get_golf_user_stats = Mock(side_effect=error("private"))
            result = collect(api)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["successful_requests"], 3)
            self.assertEqual(result["golf"]["club_stats"]["clubs"][0]["name"], "7 iron")

    def test_unrecognized_summary_keeps_aggregate_stats(self):
        api = FakeGolf({"newUnknownEnvelope": []})
        result = collect(api)
        self.assertEqual(result["golf"]["scorecard_summaries"], [])
        self.assertEqual(result["golf"]["user_stats"], {"handicap": 14})
        self.assertEqual(result["errors"][0]["code"], "unexpected_response")

    def test_round_bounds_cannot_be_bypassed_programmatically(self):
        for value in (0, -1, 101, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                collect(FakeGolf(), rounds=value)


class PrivacyTests(unittest.TestCase):
    def test_sensitive_fields_removed_recursively(self):
        value = {"access_token": "secret", "courseName": "Test", "holes": [{"Password": "secret", "emailAddress": "private", "par": 4}], "refresh-token": "secret"}
        self.assertEqual(exporter.redact_secrets(value), {"courseName": "Test", "holes": [{"par": 4}]})

    def test_private_session_ignores_existing_cache_and_restores_environment(self):
        api = Mock()
        factory = Mock(return_value=api)
        api.login.side_effect = lambda: self.assertNotIn("GARMINTOKENS", os.environ)
        api.logout.side_effect = lambda: self.assertNotIn("GARMINTOKENS", os.environ)
        with patch.dict(os.environ, {"GARMINTOKENS": "USER-EXISTING-CACHE"}), \
             patch.object(exporter.sys.stdin, "isatty", return_value=True), \
             patch.object(exporter.sys.stdout, "isatty", return_value=True), \
             patch("builtins.input", return_value="example@example.invalid"), \
             patch.object(exporter, "read_secret", return_value="TEST-PASSWORD"):
            with exporter.private_session(factory) as session:
                self.assertIs(session, api)
                self.assertIsNone(api.password)
                self.assertNotIn("GARMINTOKENS", os.environ)
            self.assertEqual(os.environ["GARMINTOKENS"], "USER-EXISTING-CACHE")
        api.login.assert_called_once_with()
        api.logout.assert_called_once_with()
        self.assertEqual(factory.call_args.kwargs["retry_attempts"], 0)

    def test_failed_login_still_clears_password_and_restores_environment(self):
        api = Mock()
        api.login.side_effect = GarminConnectAuthenticationError("private")
        with patch.dict(os.environ, {"GARMINTOKENS": "USER-EXISTING-CACHE"}), \
             patch.object(exporter.sys.stdin, "isatty", return_value=True), \
             patch.object(exporter.sys.stdout, "isatty", return_value=True), \
             patch("builtins.input", return_value="example@example.invalid"), \
             patch.object(exporter, "read_secret", return_value="TEST-PASSWORD"):
            with self.assertRaises(GarminConnectAuthenticationError):
                with exporter.private_session(Mock(return_value=api)):
                    self.fail("A failed login must not yield a session")
            self.assertEqual(os.environ["GARMINTOKENS"], "USER-EXISTING-CACHE")
        self.assertIsNone(api.password)
        api.logout.assert_called_once_with()

    def test_noninteractive_login_is_refused_without_prompting(self):
        factory = Mock()
        with patch.object(exporter.sys.stdin, "isatty", return_value=False), \
             patch("builtins.input") as prompt:
            with self.assertRaises(exporter.ExportError):
                with exporter.private_session(factory):
                    self.fail("A captured command must not prompt for credentials")
        factory.assert_not_called()
        prompt.assert_not_called()

    def test_echoing_password_fallback_is_refused(self):
        def unsafe_fallback(_):
            warnings.warn("Cannot hide password", exporter.getpass.GetPassWarning)
            return "should never reach this"
        with patch.object(exporter.getpass, "getpass", side_effect=unsafe_fallback):
            with self.assertRaises(exporter.ExportError):
                exporter.read_secret("Test password: ")


class FileAndArgumentTests(unittest.TestCase):
    def test_exports_do_not_overwrite_and_contain_no_secret_fields(self):
        with tempfile.TemporaryDirectory(prefix="garmin-golf-test-", dir=os.environ.get("OPENCODE_TEST_TMP")) as folder:
            output = Path(folder) / "exports"
            data = {"golf": {"score": 88}, "password": "TEST-SECRET"}
            first = exporter.save_export(data, output)
            second = exporter.save_export(data, output)
            self.assertNotEqual(first, second)
            self.assertEqual(len(list(output.glob("*.json"))), 2)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"golf": {"score": 88}})
            self.assertNotIn("TEST-SECRET", first.read_text(encoding="utf-8"))

    def test_invalid_json_is_not_written(self):
        with tempfile.TemporaryDirectory(prefix="garmin-golf-test-", dir=os.environ.get("OPENCODE_TEST_TMP")) as folder:
            output = Path(folder) / "exports"
            with self.assertRaises(ValueError):
                exporter.save_export({"score": float("nan")}, output)
            self.assertFalse(output.exists())

    def test_round_count_parser(self):
        self.assertEqual(exporter.round_count("20"), 20)
        for value in ("0", "101", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                exporter.round_count(value)


if __name__ == "__main__":
    unittest.main()
