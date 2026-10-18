import copy
import unittest
from pathlib import Path

from golf_data import GolfSnapshot, catalog_labels, number, percent, snapshot_from_exports


def sample(account=1, card_id=101, stamp="2026-10-01"):
    holes = [{"number": i, "strokes": 5, "putts": 2, "penalties": 0} for i in range(1, 19)]
    return {"exported_at_utc": stamp, "golf": {
        "user_stats": {"handicap": 14},
        "club_stats": [{"id": 20, "clubTypeId": 14, "clubStats": {"percentGreenHit": 25, "percentGreenMissShort": 50, "shotsCount": 1000}}],
        "scorecard_summaries": [{"id": card_id, "playerProfileId": account, "startTime": stamp, "courseName": "Test course", "holesCompleted": 18, "strokes": 90, "holePars": "4" * 18, "holes": holes}],
        "scorecards": [{"scorecard_id": str(card_id), "detail": {"scorecardDetails": [{"scorecard": {"id": card_id, "playerProfileId": account, "holesCompleted": 18, "strokes": 90, "holes": holes}, "scorecardStats": {"round": {"greensInRegulation": 6, "greensRecorded": 18, "fairwaysHit": 5, "fairwaysRecorded": 14, "putts": 36}}}]}}]}, "errors": []}


class DataTests(unittest.TestCase):
    def test_full_round_metrics_and_missing_values(self):
        model = snapshot_from_exports([(Path("one.json"), sample())])
        metrics = model.metrics()
        self.assertEqual(metrics["average_score"], 90)
        self.assertEqual(metrics["average_to_par"], 18)
        self.assertAlmostEqual(metrics["gir"], 100/3)
        self.assertEqual(metrics["putts"], 36)
        self.assertIsNone(number(True))
        self.assertIsNone(number(float("nan")))
        self.assertIsNone(percent(1, 0))

    def test_two_accounts_are_never_merged(self):
        first = sample(account=1)
        second = sample(account=2, card_id=202, stamp="2026-10-02")
        model = snapshot_from_exports([(Path("a.json"), first), (Path("b.json"), second)])
        self.assertEqual([r["id"] for r in model.rounds], ["202"])
        self.assertEqual(model.skipped_files, 1)

    def test_unknown_account_export_does_not_merge_other_accounts(self):
        blank = {"golf": {"scorecard_summaries": [], "scorecards": []}}
        model = snapshot_from_exports([(Path("a.json"), sample()), (Path("b.json"), blank)])
        self.assertEqual(model.rounds, [])

    def test_new_shots_merge_without_losing_older_rounds(self):
        old = sample(card_id=101)
        new = sample(card_id=102, stamp="2026-10-02")
        model = snapshot_from_exports([(Path("a.json"), old), (Path("b.json"), new)])
        self.assertEqual(len(model.rounds), 2)
        self.assertEqual(model.latest_three[0]["id"], "102")

    def test_standard_names_are_automatic_and_local_names_override_catalog(self):
        data = sample()
        model = snapshot_from_exports([(Path("a.json"), data)])
        self.assertEqual(model.club_label(20), ("5 iron", "Garmin standard club type"))
        data["golf"]["club_types"] = [{"id": 14, "name": "5 Iron"}]
        model = snapshot_from_exports([(Path("a.json"), data)], {"20": "My iron"})
        self.assertEqual(model.club_label(20), ("My iron", "Local label"))
        self.assertEqual(model.club_label(0)[0], "Unassigned club")

    def test_standard_iron_type_numbers_are_not_off_by_one(self):
        expected = {10: "1 iron", 11: "2 iron", 12: "3 iron", 13: "4 iron", 14: "5 iron", 15: "6 iron", 16: "7 iron", 17: "8 iron", 18: "9 iron"}
        model = GolfSnapshot(clubs={str(k): {"clubTypeId": k} for k in expected})
        for kind, name in expected.items():
            with self.subTest(kind=kind):
                self.assertEqual(model.club_label(kind)[0], name)

    def test_standard_woods_hybrids_wedges_and_putter(self):
        expected = {1: "Driver", 2: "3 wood", 3: "5 wood", 6: "3 hybrid", 19: "Pitching wedge", 20: "Gap wedge", 21: "Sand wedge", 22: "Lob wedge", 23: "Putter", 26: "7 wood", 36: "7 hybrid"}
        model = GolfSnapshot(clubs={str(k): {"clubTypeId": k} for k in expected})
        for kind, name in expected.items():
            with self.subTest(kind=kind):
                self.assertEqual(model.club_label(kind)[0], name)

    def test_garmin_custom_names_are_not_replaced_by_standard_labels(self):
        model = GolfSnapshot(clubs={"123": {"clubTypeId": 20, "name": "48 Degree "}}, type_labels={"20": "Gap Wedge"})
        self.assertEqual(model.club_label(123), ("48 Degree", "Garmin custom name"))

    def test_live_catalog_has_priority_over_bundled_catalog(self):
        model = GolfSnapshot(clubs={"123": {"clubTypeId": 15}}, type_labels={"15": "6 Iron"})
        self.assertEqual(model.club_label(123), ("6 Iron", "Garmin type catalog"))

    def test_official_club_types_export_envelope_is_supported(self):
        payload = {"version": "v1", "type": "CLUB_TYPES", "data": [{"value": 15, "name": "6 Iron", "valid": True}, {"value": 0, "name": "Unknown", "valid": False}]}
        self.assertEqual(catalog_labels(payload), {"15": "6 Iron"})

    def test_unrecognized_future_types_are_not_assigned_a_fake_club(self):
        model = GolfSnapshot(clubs={"123": {"clubTypeId": 999}})
        self.assertEqual(model.club_label(123)[0], "Unknown club")

    def test_approach_and_aggregate_views_both_get_readable_names(self):
        data = sample()
        data["golf"]["scorecards"][0]["shots"] = {"holeShots": [{"holeNumber": 1, "shots": [{"shotType": "APPROACH", "clubId": 20, "endLoc": {"lie": "Rough"}}]}]}
        model = snapshot_from_exports([(Path("a.json"), data)])
        self.assertEqual(model.aggregate_clubs()[0]["label"], "5 iron")
        approaches = model.approach_analysis()
        self.assertEqual(approaches["clubs"][0]["label"], "5 iron")
        self.assertEqual(approaches["shots"][0]["club"], "5 iron")

    def test_approach_counts_do_not_treat_missing_outcomes_as_misses(self):
        data = sample()
        data["golf"]["scorecards"][0]["shots"] = {"holeShots": [{"holeNumber": 1, "shots": [
            {"shotType": "APPROACH", "clubId": 20, "endLoc": {"lie": "Green"}},
            {"shotType": "APPROACH", "clubId": 20, "endLoc": {"lie": "Rough"}},
            {"shotType": "APPROACH", "clubId": 20, "endLoc": {"lie": "Unknown"}},
            {"shotType": "RECOVERY", "clubId": 20, "endLoc": {"lie": "Rough"}},
            {"shotType": "APPROACH", "clubId": 20, "excludeFromStats": True, "endLoc": {"lie": "Rough"}},
            {"shotType": "APPROACH", "clubId": 0, "endLoc": {"lie": "Green"}},
        ]}]}
        model = snapshot_from_exports([(Path("a.json"), data)])
        result = model.approach_analysis()
        self.assertEqual(result["approaches"], 4)
        self.assertEqual(result["shot_holes"], 1)
        self.assertEqual(result["expected_holes"], 18)
        self.assertEqual(result["unassigned"], 1)
        row = next(x for x in result["clubs"] if x["id"] == "20")
        self.assertEqual((row["green"], row["miss"], row["unknown"]), (1, 1, 1))
        self.assertEqual(row["green_percent"], 50)

    def test_nine_hole_round_is_not_in_eighteen_hole_average(self):
        full = sample()
        half = sample(card_id=102, stamp="2026-10-02")
        half["golf"]["scorecard_summaries"][0]["holesCompleted"] = 9
        half["golf"]["scorecards"][0]["detail"]["scorecardDetails"][0]["scorecard"]["holesCompleted"] = 9
        model = snapshot_from_exports([(Path("a.json"), full), (Path("b.json"), half)])
        self.assertEqual(model.metrics()["rounds"], 1)
        self.assertEqual(len(model.latest_three), 2)

    def test_later_summary_only_import_keeps_earlier_detailed_shots(self):
        first = sample()
        first["golf"]["scorecards"][0]["shots"] = {"holeShots": [{"holeNumber": 1, "shots": [{"shotType": "APPROACH", "clubId": 20, "endLoc": {"lie": "Green"}}]}]}
        second = copy.deepcopy(first)
        second["exported_at_utc"] = "2026-10-02"
        del second["golf"]["scorecards"][0]["shots"]
        model = snapshot_from_exports([(Path("a.json"), first), (Path("b.json"), second)])
        self.assertEqual(model.approach_analysis()["approaches"], 1)


if __name__ == "__main__":
    unittest.main()
