import json
import os
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

from golf_data import GolfSnapshot,load_snapshot
from golf_history import RoundSelection,default_trend_keys,load_selection,moving_average,period_statistics,save_selection,trend_series
from test_golf_game import round_fixture


def history_fixture(count=35):
    rounds=[]
    for i in range(count):
        r=round_fixture(str(i+1),(date(2026,1,1)+timedelta(days=i)).isoformat())
        r["score"]=100-i
        r["to_par"]=r["score"]-r["par"]
        rounds.append(r)
    return GolfSnapshot(rounds=list(reversed(rounds)),account_identities=frozenset({"test-account"}),clubs={"10":{"clubTypeId":1},"20":{"clubTypeId":19},"30":{"clubTypeId":22,"name":"58 Degree"},"40":{"clubTypeId":14}})


class SelectionTests(unittest.TestCase):
    def test_latest_ten_twenty_thirty_and_custom(self):
        model=history_fixture()
        for count in (1,10,20,30,17):
            with self.subTest(count=count):
                rounds=RoundSelection(count=count).resolve(model)
                self.assertEqual(len(rounds),count)
                self.assertEqual(rounds[0]["id"],"35")
                self.assertEqual(rounds[-1]["id"],str(36-count))

    def test_missing_imports_are_reported_not_fabricated(self):
        model=history_fixture(12)
        selection=RoundSelection(count=30)
        self.assertEqual(len(selection.resolve(model)),12)
        self.assertEqual(selection.summary(model)["requested"],30)
        self.assertTrue(selection.summary(model)["shortfall"])

    def test_manual_choice_deduplicates_and_orders_by_date(self):
        model=history_fixture()
        selected=RoundSelection("manual",ids=("1","20","3","20")).resolve(model)
        self.assertEqual([r["id"] for r in selected],["20","3","1"])

    def test_all_and_completed_hole_filter(self):
        model=history_fixture(3)
        half=round_fixture("half","2026-12-01")
        half["holes_completed"]=9
        model.rounds.insert(0,half)
        active=round_fixture("active","2026-12-02")
        active["in_progress"]=True
        model.rounds.insert(0,active)
        self.assertEqual(len(RoundSelection("all",full_only=True).resolve(model)),3)
        self.assertEqual(len(RoundSelection("all",full_only=False).resolve(model)),4)
        self.assertEqual(len(RoundSelection("all").resolve(model)),4)

    def test_invalid_counts_and_mutable_ids_rejected(self):
        for count in (0,-1,10001,True,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):
                RoundSelection(count=count)
        with self.assertRaises(ValueError):
            RoundSelection("manual",ids=["1"])

    def test_preferences_are_account_scoped(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP")) as tmp:
            path=Path(tmp)/"round-selection.json"
            selected=RoundSelection("manual",ids=("1","3"),full_only=False)
            save_selection(path,selected,{"account-one"})
            self.assertEqual(load_selection(path,{"account-one"}),selected)
            self.assertEqual(load_selection(path,{"account-two"}),RoundSelection())
            path.write_text('{"version":1,"accounts":["account-one"],"count":0}',encoding="utf-8")
            self.assertEqual(load_selection(path,{"account-one"}),RoundSelection())

    def test_all_imported_history_is_not_silently_limited_to_a_hundred_files(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP")) as tmp:
            folder=Path(tmp)
            for i in range(105):
                data={"exported_at_utc":f"2026-{i:04d}","golf":{"scorecard_summaries":[{"id":i+1,"playerProfileId":"fake-account","startTime":str(i),"holesCompleted":18,"strokes":90}],"scorecards":[]}}
                (folder/f"export-{i:03d}.json").write_text(json.dumps(data),encoding="utf-8")
            self.assertEqual(len(load_snapshot(folder).rounds),105)

    def test_generic_count_survives_the_first_account_import(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP")) as tmp:
            path=Path(tmp)/"round-selection.json"
            selection=RoundSelection(count=30,full_only=True)
            save_selection(path,selection,set())
            self.assertEqual(load_selection(path,{"new-account"}),selection)


class TrendTests(unittest.TestCase):
    def test_manual_trends_are_oldest_to_newest(self):
        model=history_fixture()
        rounds=RoundSelection("manual",ids=("20","1","3")).resolve(model)
        series=trend_series(rounds,"score18")
        self.assertEqual([p["id"] for p in series["slots"]],["1","3","20"])

    def test_missing_values_are_gaps_not_zero(self):
        model=history_fixture(6)
        model.rounds[3]["score"]=None
        series=trend_series(model.rounds,"score18")
        self.assertEqual(len(series["slots"]),6)
        self.assertEqual(len(series["points"]),5)
        self.assertEqual(series["missing"],1)
        self.assertIsNone(series["slots"][2]["value"])

    def test_rolling_average_needs_a_complete_recorded_window(self):
        slots=[{"value":v} for v in (1,2,3,None,5,6,7)]
        self.assertEqual(moving_average(slots,3),[None,None,2,None,None,None,6])

    def test_nine_and_eighteen_hole_scores_are_not_mixed(self):
        model=history_fixture(1)
        half=round_fixture("half","2026-12-01")
        half.update(holes_completed=9,score=40,putts=18)
        stats=period_statistics([model.rounds[0],half])
        self.assertEqual(stats["average_score"],100)
        self.assertEqual(stats["putts"],36)
        self.assertEqual(stats["scoring_holes"],18)
        self.assertEqual(trend_series([half,model.rounds[0]],"score18")["excluded"],1)
        self.assertEqual(default_trend_keys([half])[0],"score9")
        self.assertIn("score9",default_trend_keys([half,model.rounds[0]]))
        self.assertIn("score18",default_trend_keys([half,model.rounds[0]]))
        self.assertEqual(period_statistics([half])["average_score"],40)

    def test_rate_summary_is_weighted_by_recorded_opportunities(self):
        a,b=history_fixture(2).rounds
        a.update(greens_hit=9,greens_recorded=10)
        b.update(greens_hit=1,greens_recorded=2)
        self.assertAlmostEqual(period_statistics([a,b])["gir"],100*10/12)
        series=trend_series([a,b],"gir")
        self.assertAlmostEqual(series["average"],100*10/12)
        self.assertAlmostEqual(moving_average(series["slots"],2)[-1],100*10/12)

    def test_complete_tracking_is_required_for_penalty_and_threeputt_trends(self):
        r=history_fixture(1).rounds[0]
        r.update(penalties=0,penalty_coverage=17,putt_coverage=17,three_putts=0)
        self.assertEqual(trend_series([r],"penalties18")["missing"],1)
        self.assertEqual(trend_series([r],"three_putts18")["missing"],1)
        r.update(penalty_coverage=18,putt_coverage=18)
        self.assertEqual(trend_series([r],"penalties18")["points"][0]["value"],0)

    def test_direction_of_change_respects_metric(self):
        rounds=history_fixture(10).rounds
        self.assertTrue(trend_series(rounds,"score18")["improving"])
        for i,r in enumerate(reversed(rounds)):
            r.update(greens_hit=i+1,greens_recorded=18)
        self.assertTrue(trend_series(rounds,"gir")["improving"])


if __name__=="__main__":
    unittest.main()
