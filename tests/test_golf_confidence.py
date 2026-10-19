import unittest

from golf_confidence import club_confidence,club_history,wilson_interval
from test_golf_game import model_fixture,round_fixture


class ClubConfidenceTests(unittest.TestCase):
    def test_role_counts_do_not_mix_tees_and_approaches(self):
        model=model_fixture()
        approaches=club_confidence(model,model.rounds,"Approaches")
        tees=club_confidence(model,model.rounds,"Tee fairways")
        self.assertNotIn("Driver",[r["label"] for r in approaches["rows"]])
        self.assertEqual(tees["rows"][0]["label"],"Driver")
        self.assertEqual(tees["hits"],1)

    def test_small_perfect_sample_does_not_become_reliable_confidence(self):
        model=model_fixture()
        report=club_confidence(model,model.rounds,"Approaches")
        self.assertIsNone(report["strongest"])
        self.assertFalse(any(r["enough"] for r in report["rows"]))
        low,high=wilson_interval(1,1)
        self.assertLess(low,25)
        self.assertAlmostEqual(high,100)

    def test_more_complete_records_provide_more_evidence(self):
        model=model_fixture()
        model.rounds=[round_fixture(str(i),f"2026-10-{i+1:02d}") for i in range(12)]
        report=club_confidence(model,model.rounds,"Tee fairways")
        self.assertEqual(report["strongest"]["label"],"Driver")
        self.assertEqual(report["strongest"]["classified"],12)

    def test_unknown_finishes_are_not_misses(self):
        model=model_fixture()
        report=club_confidence(model,model.rounds,"Approaches")
        row=next(r for r in report["rows"] if r["label"]=="58 Degree")
        self.assertEqual((row["hits"],row["misses"],row["unknown"]),(0,0,1))
        self.assertIsNone(row["rate"])

    def test_chips_are_not_up_and_down_and_keep_empty_clubs_unmeasured(self):
        model=model_fixture()
        model.clubs["35"]={"clubTypeId":21,"name":"54 Degree"}
        report=club_confidence(model,model.rounds,"Wedge chips",show_empty=True)
        row=next(r for r in report["rows"] if r["label"]=="54 Degree")
        self.assertEqual(row["records"],0)
        self.assertIsNone(row["rate"])
        self.assertIsNone(row["low"])

    def test_putting_is_per_hole_and_excludes_zero_putt_chipins(self):
        model=model_fixture()
        model.rounds[0]["holes"][0]["putts"]=0
        model.rounds[0]["holes"][1]["putts"]=3
        report=club_confidence(model,model.rounds,"Putting")
        self.assertEqual((report["hits"],report["misses"]),(16,1))
        self.assertEqual(report["rows"][0]["classified"],17)

    def test_club_history_has_gaps_when_a_club_has_no_classified_shots(self):
        model=model_fixture()
        blank=round_fixture("blank","2026-10-02")
        blank["shots"]={}
        blank["shot_holes"]=0
        model.rounds.append(blank)
        history=club_history(model,model.rounds,"Tee fairways","10")
        self.assertEqual([p["value"] for p in history["rate"]["slots"]],[100,None])
        self.assertEqual([p["value"] for p in history["misses"]["slots"]],[0,None])
        self.assertEqual(history["rate"]["slots"][0]["classified"],1)

    def test_unassigned_clubs_do_not_get_ranked_as_confident_named_clubs(self):
        model=model_fixture()
        shots=model.rounds[0]["shots"]["holeShots"][0]["shots"]
        shots[:]=[{"id":i,"shotType":"APPROACH","clubId":0,"endLoc":{"lie":"Green"}} for i in range(20)]
        result=club_confidence(model,model.rounds,"Approaches")
        unassigned=next(r for r in result["rows"] if r["id"]=="0")
        self.assertEqual(unassigned["hits"],20)
        self.assertFalse(unassigned["enough"])
        self.assertNotEqual((result["strongest"] or {}).get("id"),"0")

    def test_duplicate_approach_records_do_not_inflate_good_shot_counts(self):
        model=model_fixture()
        shots=model.rounds[0]["shots"]["holeShots"][2]["shots"]
        shots.append(dict(shots[0]))
        report=club_confidence(model,model.rounds,"Approaches")
        row=next(r for r in report["rows"] if r["label"]=="Pitching wedge")
        self.assertEqual(row["hits"],1)


if __name__=="__main__":
    unittest.main()
