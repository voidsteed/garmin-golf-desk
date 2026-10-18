import copy
import unittest

from golf_coaching import improvement_snapshot
from golf_data import GolfSnapshot
from golf_game import full_game_snapshot


def round_fixture(key="1", day="2026-10-01"):
    holes = [{"number":n,"par":4,"strokes":5,"to_par":1,"putts":2,"penalties":0,"fairwayShotOutcome":"HIT"} for n in range(1,19)]
    holes[1].update(par=3,to_par=2)
    return {"id":key,"date":day,"sort_date":day,"course":"Test course","holes_completed":18,"in_progress":False,
            "score":90,"par":71,"to_par":19,"fairways_hit":10,"fairways_recorded":14,"greens_hit":6,"greens_recorded":18,
            "putts":36,"putt_coverage":18,"penalties":0,"penalty_coverage":18,"three_putts":0,"big_holes":[holes[1]],
            "holes":holes,"shot_holes":6,"shots":{"holeShots":[
                {"holeNumber":1,"shots":[{"id":1,"shotType":"TEE","shotOrder":1,"clubId":10,"startLoc":{"lie":"TeeBox"},"endLoc":{"lie":"Fairway"},"meters":200}]},
                {"holeNumber":2,"shots":[{"id":2,"shotType":"APPROACH","shotOrder":1,"clubId":40,"startLoc":{"lie":"TeeBox"},"endLoc":{"lie":"Green"},"meters":140}]},
                {"holeNumber":3,"shots":[{"id":3,"shotType":"APPROACH","clubId":20,"endLoc":{"lie":"Green"},"meters":60}]},
                {"holeNumber":4,"shots":[{"id":4,"shotType":"CHIP","clubId":30,"endLoc":{"lie":"Rough"},"meters":10}]},
                {"holeNumber":5,"shots":[{"id":5,"shotType":"APPROACH","clubId":30,"endLoc":{"lie":"Unknown"},"meters":50}]},
                {"holeNumber":6,"shots":[{"id":6,"shotType":"RECOVERY","clubId":20,"startLoc":{"lie":None},"endLoc":{"lie":"Fairway"},"meters":30}]},
            ]}}


def model_fixture():
    return GolfSnapshot(rounds=[round_fixture()],clubs={"10":{"clubTypeId":1},"20":{"clubTypeId":19},"30":{"clubTypeId":22,"name":"58 Degree"},"40":{"clubTypeId":14}})


class FullGameTests(unittest.TestCase):
    def test_driver_fairways_and_recorded_distance(self):
        model = model_fixture()
        result = full_game_snapshot(model)
        driver = next(r for r in result["tee"] if r["driver"])
        self.assertEqual(driver["label"],"Driver")
        self.assertEqual((driver["hit"],driver["fw_recorded"]),(1,1))
        self.assertAlmostEqual(driver["average_yards"],200/0.9144)
        self.assertEqual(driver["average_yards"],driver["median_yards"])

    def test_par_three_tee_approach_is_not_a_fairway_attempt(self):
        row = next(r for r in full_game_snapshot(model_fixture())["tee"] if r["id"]=="40")
        self.assertEqual(row["label"],"5 iron")
        self.assertEqual(row["par3_tees"],1)
        self.assertEqual(row["fw_recorded"],0)
        self.assertIsNone(row["fw_percent"])

    def test_retee_holes_do_not_get_ambiguous_fairway_attribution(self):
        model = model_fixture()
        model.rounds[0]["shots"]["holeShots"][0]["shots"].append({"id":9,"shotType":"TEE","clubId":40,"meters":130})
        result = full_game_snapshot(model)
        self.assertEqual(result["ambiguous_tee_holes"],1)
        self.assertEqual(sum(r["fw_recorded"] for r in result["tee"]),0)

    def test_scorecard_fairway_is_not_guessed_from_end_lie(self):
        model = model_fixture()
        model.rounds[0]["holes"][0]["fairwayShotOutcome"]="LEFT"
        driver = next(r for r in full_game_snapshot(model)["tee"] if r["driver"])
        self.assertEqual((driver["hit"],driver["left"]),(0,1))

    def test_wedge_approaches_chips_and_recoveries_remain_separate(self):
        result = full_game_snapshot(model_fixture())
        pitch = next(r for r in result["wedges"] if r["id"]=="20")
        lob = next(r for r in result["wedges"] if r["id"]=="30")
        self.assertEqual(pitch["label"],"Pitching wedge")
        self.assertEqual((pitch["approach"]["shots"],pitch["other"]),(1,1))
        self.assertEqual(pitch["approach_green_percent"],100)
        self.assertEqual((lob["approach"]["shots"],lob["chip"]["shots"]),(1,1))
        self.assertIsNone(lob["approach_green_percent"])
        self.assertEqual(lob["chip_green_percent"],0)
        self.assertAlmostEqual(lob["chip_average_yards"],10/0.9144)
        self.assertAlmostEqual(lob["approach_average_yards"],50/0.9144)

    def test_putting_uses_scorecards_not_sensor_shot_count(self):
        model = model_fixture()
        model.rounds[0]["shots"]["holeShots"][0]["shots"].append({"id":19,"shotType":"PUTT","clubId":99,"meters":8})
        result = full_game_snapshot(model)
        self.assertEqual(result["average_putts"],36)
        self.assertEqual(result["tracked_putting_holes"],18)
        self.assertEqual(result["putts_per_tracked_hole"],2)
        self.assertEqual(result["three_putts_per_full_round"],0)

    def test_bag_wedges_without_exported_records_still_show_as_unmeasured(self):
        model = model_fixture()
        model.clubs["35"]={"clubTypeId":21,"name":"54 Degree"}
        row = next(r for r in full_game_snapshot(model)["wedges"] if r["id"]=="35")
        self.assertEqual(row["label"],"54 Degree")
        self.assertEqual(row["approach"]["shots"],0)
        self.assertIsNone(row["approach_green_percent"])
        self.assertIsNone(row["chip_average_yards"])

    def test_incomplete_putting_is_not_treated_as_zero_three_putts(self):
        model = model_fixture()
        model.rounds[0]["holes"][0].pop("putts")
        model.rounds[0]["putt_coverage"]=17
        self.assertIsNone(full_game_snapshot(model)["three_putts_per_full_round"])
        self.assertIsNone(model.metrics()["three_putts"])

    def test_duplicate_shots_and_excluded_shots_do_not_inflate_counts(self):
        model = model_fixture()
        shots = model.rounds[0]["shots"]["holeShots"][2]["shots"]
        shots.append(copy.deepcopy(shots[0]))
        shots.append({"id":99,"shotType":"APPROACH","clubId":20,"excludeFromStats":True,"endLoc":{"lie":"Rough"}})
        result = full_game_snapshot(model)
        self.assertEqual(result["wedge_approaches"],2)

    def test_improvement_scope_and_starter_goals_are_explicit(self):
        model = model_fixture()
        model.rounds = [round_fixture(str(n),f"2026-10-0{n}") for n in (4,3,2,1)]
        latest = improvement_snapshot(model)
        all_rounds = improvement_snapshot(model,latest_three=False)
        self.assertEqual(len(latest["rounds"]),3)
        self.assertEqual(len(all_rounds["rounds"]),4)
        self.assertEqual({r["key"]:r["goal"] for r in latest["priorities"]},{"three_putts":2,"penalties":1,"big_holes":3})

    def test_missing_hole_scores_do_not_appear_as_zero_big_holes(self):
        model = model_fixture()
        model.rounds[0]["holes"] = []
        model.rounds[0]["big_holes"] = []
        self.assertIsNone(model.metrics()["big_holes"])


if __name__=="__main__":
    unittest.main()
