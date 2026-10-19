import copy
import unittest

from golf_research import approach_context,meters_between,practice_summary,putting_context,rating_proxy,reference_results,research_snapshot,scoring_breakdown,tracking_audit,validated_scale
from golf_research_store import hole_signature,round_signatures,shot_signature,usable_shots
from test_golf_baselines import synthetic_reference
from test_golf_game import model_fixture


def sign_scope(model,scope):
    for r in model.rounds:
        if r["id"] in scope.get("rounds",{}):
            scope["rounds"][r["id"]]["source_signatures"]=round_signatures(r)
        for h in r["holes"]:
            note=scope.get("holes",{}).get(r["id"],{}).get(str(h["number"]))
            if note is not None:
                note["source_signature"]=hole_signature(r,h)
        for h,s,key in usable_shots(r):
            note=scope.get("shots",{}).get(r["id"],{}).get(key)
            if note is not None:
                note["source_signature"]=shot_signature(r,h,s)
    return scope


class ResearchTests(unittest.TestCase):
    def test_big_hole_categories_are_mutually_exclusive_and_missing_is_unknown(self):
        model=model_fixture()
        r=model.rounds[0]
        for h in r["holes"]:
            h.update(strokes=h["par"],putts=2,penalties=0)
        for h in r["holes"][:5]:
            h["strokes"]=h["par"]+2
        r["holes"][0].update(penalties=1,putts=3)
        r["holes"][1]["penalties"]=1
        r["holes"][2]["putts"]=3
        r["holes"][4].pop("penalties")
        data=scoring_breakdown(model.rounds)
        self.assertEqual(len(data["big_holes"]),5)
        self.assertEqual(sum(data["flags"].values()),5)
        self.assertEqual(data["flags"],{"Penalty + three-putt":1,"Penalty only":1,"Three-putt only":1,"Neither flag recorded":1,"Unknown tracking":1})
        self.assertEqual(sum(row["holes"] for row in data["flag_costs"].values()),5)
        self.assertEqual(sum(row["over_par"] for row in data["flag_costs"].values()),10)
        self.assertEqual(sum(row["gross_strokes"] for row in data["flag_costs"].values()),sum(row["score"] for row in data["big_holes"]))

    def test_triple_cap_is_a_bookkeeping_scenario_not_an_additive_forecast(self):
        model=model_fixture()
        h=model.rounds[0]["holes"][0]
        h["strokes"]=h["par"]+5
        data=scoring_breakdown(model.rounds)
        self.assertEqual(data["cap_scenario"],3)
        self.assertEqual(data["triple_plus"],1)
        self.assertEqual(sum(row["above_double"] for row in data["flag_costs"].values()),3)

    def test_audit_does_not_turn_review_acknowledgments_into_valid_data(self):
        model=model_fixture()
        scope={"reviews":{"verify-putts:1":"Verified"}}
        data=tracking_audit(model,model.rounds,scope)
        self.assertEqual(data["facts"]["reviewed_rounds"],0)
        self.assertTrue(any(x["key"]=="shot-holes:1" for x in data["items"]))
        self.assertTrue(any(x["key"]=="gps-putts:1" and x["severity"]=="Info" for x in data["items"]))

    def test_missing_penalty_entries_are_never_zero_filled(self):
        model=model_fixture()
        model.rounds[0]["holes"][0].pop("penalties")
        data=tracking_audit(model,model.rounds,{})
        self.assertEqual(data["facts"]["penalty_holes"],17)
        self.assertTrue(any(x["title"]=="Missing penalty entries" for x in data["items"]))

    def test_first_putt_context_includes_successful_holes_as_denominators(self):
        model=model_fixture()
        model.rounds[0]["holes"][1]["putts"]=3
        scope={"holes":{"1":{"1":{"first_putt_bin":"15–30 ft"},"2":{"first_putt_bin":"15–30 ft"}}}}
        sign_scope(model,scope)
        data=putting_context(model.rounds,scope)
        self.assertEqual(data["groups"][0]["holes"],2)
        self.assertEqual(data["groups"][0]["rate"],50)

    def test_coordinate_scale_validation_needs_consistent_real_endpoint_lengths(self):
        model=model_fixture()
        r=model.rounds[0]
        holes=[]
        for i in range(3):
            a=(40+i*.001,-75)
            b=(a[0]+.001,a[1])
            holes.append({"holeNumber":i+1,"pinPosition":{"lat":a[0]+.003,"lon":a[1]},"shots":[{"id":i,"shotType":"APPROACH","clubId":40,"startLoc":{"lat":a[0],"lon":a[1],"lie":"Fairway"},"endLoc":{"lat":b[0],"lon":b[1],"lie":"Green"},"meters":meters_between(a,b)}]})
        r["shots"]={"holeShots":holes}
        self.assertEqual(validated_scale(r)["name"],"degrees")
        contexts=approach_context(model,[r],{})
        self.assertEqual(contexts["unknown_distance"],0)
        self.assertTrue(all(x["distance_source"]=="Recorded-pin proxy" for x in contexts["records"]))
        holes[0]["shots"][0]["meters"]*=10
        holes[1]["shots"][0]["meters"]*=10
        self.assertIsNone(validated_scale(r))

    def test_context_unknowns_stay_unknown_and_intent_filter_is_explicit(self):
        model=model_fixture()
        source=approach_context(model,model.rounds,{})
        self.assertTrue(source["unknown_distance"])
        scope={"shots":{"1":{"2":{"intent":"Lay-up"}}}}
        filtered=approach_context(model,model.rounds,scope,True)
        self.assertEqual(len(filtered["records"]),len(source["records"])-1)

    def test_normal_mishits_are_kept_and_only_tracking_errors_are_excluded(self):
        model=model_fixture()
        base={"club_id":"40","role":"Full swing","session":"Matched A","lie":"Range","conditions":"Calm / level"}
        rows=[{**base,"carry_yards":150,"lateral_yards":5,"contact":"Normal attempt"},{**base,"carry_yards":30,"lateral_yards":-20,"contact":"Mishit"},{**base,"carry_yards":400,"lateral_yards":0,"contact":"Tracking error"}]
        data=practice_summary(model,{"practice":rows})
        self.assertEqual(data["carry"][0]["n"],2)
        self.assertEqual(data["carry"][0]["median"],90)
        self.assertEqual(data["carry"][0]["mishits"],1)
        self.assertEqual(len(data["carry"][0]["paired_samples"]),2)

    def test_no_reference_produces_no_synthetic_sg(self):
        model=model_fixture()
        data=reference_results(model,model.rounds,{})
        self.assertIsNone(data["reference"])
        self.assertEqual(data["putting"],[])
        self.assertEqual(data["shots"],[])

    def test_putting_sg_requires_exact_distance_basis_and_verified_counts(self):
        model=model_fixture()
        scope={"baseline":synthetic_reference().to_dict(),"holes":{"1":{"1":{"first_putt_feet":30,"distance_basis":"Measured","strokes_from_first_putt":2}}}}
        self.assertEqual(reference_results(model,model.rounds,scope)["putting"],[])
        scope["rounds"]={"1":{"putts_status":"Verified"}}
        sign_scope(model,scope)
        data=reference_results(model,model.rounds,scope)
        self.assertEqual(data["putting"][0]["sg"],0)
        scope["holes"]["1"]["1"]={"first_putt_bin":"15–30 ft"}
        self.assertEqual(reference_results(model,model.rounds,scope)["putting"],[])

    def test_shot_sg_blocks_unallocated_or_unverified_penalties(self):
        model=model_fixture()
        model.rounds[0]["holes"][0]["penalties"]=1
        note={"states_verified":True,"start_yards":150,"start_lie":"Fairway","end_yards":10,"end_lie":"Green","holed":False}
        scope={"baseline":synthetic_reference().to_dict(),"rounds":{"1":{"penalties_status":"Verified"}},"shots":{"1":{"1":note}}}
        sign_scope(model,scope)
        self.assertEqual(reference_results(model,model.rounds,scope)["shots"],[])
        note.update(penalty_strokes=1,review_status="Unchecked")
        self.assertEqual(reference_results(model,model.rounds,scope)["shots"],[])
        note["review_status"]="Verified"
        self.assertAlmostEqual(reference_results(model,model.rounds,scope)["shots"][0]["sg"],-.8)

    def test_blank_immediate_penalty_is_not_silently_zero(self):
        model=model_fixture()
        note={"states_verified":True,"start_yards":150,"start_lie":"Fairway","end_yards":10,"end_lie":"Green","holed":False}
        scope=sign_scope(model,{"baseline":synthetic_reference().to_dict(),"rounds":{"1":{"penalties_status":"Verified"}},"shots":{"1":{"1":note}}})
        self.assertEqual(reference_results(model,model.rounds,scope)["shots"],[])
        note["penalty_strokes"]=0
        self.assertEqual(len(reference_results(model,model.rounds,scope)["shots"]),1)

    def test_source_shot_changes_block_previously_checked_states(self):
        model=model_fixture()
        note={"states_verified":True,"start_yards":150,"start_lie":"Fairway","end_yards":10,"end_lie":"Green","holed":False,"penalty_strokes":0}
        scope=sign_scope(model,{"baseline":synthetic_reference().to_dict(),"rounds":{"1":{"penalties_status":"Verified"}},"shots":{"1":{"1":note}}})
        self.assertEqual(len(reference_results(model,model.rounds,scope)["shots"]),1)
        model.rounds[0]["shots"]["holeShots"][0]["shots"][0]["meters"]+=1
        data=reference_results(model,model.rounds,scope)
        self.assertEqual(data["shots"],[])
        self.assertIn("source shot changed",data["blocked"][0]["reason"])

    def test_missing_par_does_not_erase_known_putting_holes(self):
        model=model_fixture()
        model.rounds[0]["holes"][0]["par"]=None
        data=scoring_breakdown(model.rounds)
        self.assertEqual(data["scored_holes"],17)
        self.assertEqual(data["tracked_putt_holes"],18)

    def test_negative_counts_are_unknown_not_successful_holes(self):
        model=model_fixture()
        model.rounds[0]["holes"][1].update(putts=-1,penalties=-1)
        data=scoring_breakdown(model.rounds)
        self.assertEqual(data["tracked_putt_holes"],17)
        self.assertEqual(data["flags"]["Unknown tracking"],1)

    def test_first_putt_sequence_includes_recoveries_and_requires_finish_count(self):
        model=model_fixture()
        note={"first_putt_feet":30,"distance_basis":"Measured"}
        scope=sign_scope(model,{"baseline":synthetic_reference().to_dict(),"rounds":{"1":{"putts_status":"Verified"}},"holes":{"1":{"1":note}}})
        self.assertEqual(reference_results(model,model.rounds,scope)["putting"],[])
        note["strokes_from_first_putt"]=3
        data=reference_results(model,model.rounds,scope)
        self.assertEqual(data["putting"][0]["sg"],-1)

    def test_outdated_first_putt_notes_are_retained_but_not_analyzed(self):
        model=model_fixture()
        scope=sign_scope(model,{"holes":{"1":{"1":{"first_putt_bin":"15–30 ft"}}}})
        self.assertEqual(len(putting_context(model.rounds,scope)["holes"]),1)
        model.rounds[0]["holes"][0]["putts"]=3
        self.assertEqual(putting_context(model.rounds,scope)["holes"],[])
        self.assertEqual(scope["holes"]["1"]["1"]["first_putt_bin"],"15–30 ft")

    def test_practice_groups_do_not_pool_different_dates_or_lies(self):
        model=model_fixture()
        base={"club_id":"40","role":"Full swing","session":"Repeated label","conditions":"Calm / level","carry_yards":150}
        rows=[{**base,"date":"2026-10-01","lie":"Range"},{**base,"date":"2026-10-02","lie":"Range"},{**base,"date":"2026-10-02","lie":"Rough"}]
        self.assertEqual(len(practice_summary(model,{"practice":rows})["carry"]),3)

    def test_rating_proxy_is_not_computed_without_valid_inputs_or_for_nine_holes(self):
        model=model_fixture()
        r=model.rounds[0]
        self.assertEqual(rating_proxy([r])["missing"],1)
        r.update(course_rating=72,slope_rating=113,score=90)
        self.assertEqual(rating_proxy([r])["points"][0]["value"],18)
        half=copy.deepcopy(r)
        half["holes_completed"]=9
        self.assertEqual(rating_proxy([half])["slots"],[])

    def test_recommendations_use_selected_data_without_mutating_it(self):
        model=model_fixture()
        before=copy.deepcopy(model.rounds)
        data=research_snapshot(model,model.rounds,{})
        self.assertEqual(data["stats"]["selected"],1)
        self.assertTrue(data["cards"])
        self.assertEqual(model.rounds,before)


if __name__=="__main__":
    unittest.main()
