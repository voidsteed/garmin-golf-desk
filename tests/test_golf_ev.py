import unittest

from golf_ev import Outcome,ShotPlan,compare_plans,expected_strokes,plan_sensitivity,shift_error


class EvTests(unittest.TestCase):
    def test_current_stroke_and_immediate_penalty_are_counted_once(self):
        plan = ShotPlan("A",(Outcome(.8,2),Outcome(.2,3,1)))
        self.assertAlmostEqual(expected_strokes(plan),3.4)

    def test_positive_ev_means_lower_expected_strokes(self):
        first = ShotPlan("Current",(Outcome(.5,2),Outcome(.5,4)))
        second = ShotPlan("Safer",(Outcome(.8,2),Outcome(.2,4)))
        result = compare_plans(first,second,error_radius=0,remaining_uncertainty=0,error_index=1)
        self.assertEqual(result["best_estimate"],"Safer")
        self.assertAlmostEqual(result["alternative_ev"],.6)
        self.assertEqual(result["robust_preference"],"Safer")

    def test_overlapping_or_incomplete_probabilities_are_not_normalized_away(self):
        with self.assertRaises(ValueError):
            expected_strokes(ShotPlan("Bad",(Outcome(.7,2),Outcome(.7,3))))

    def test_error_stress_preserves_probability_total(self):
        plan = ShotPlan("A",(Outcome(.6,2),Outcome(.2,3),Outcome(.15,4),Outcome(.05,4,1)))
        stressed = shift_error(plan,.1)
        self.assertAlmostEqual(sum(o.probability for o in stressed.outcomes),1)
        self.assertAlmostEqual(stressed.outcomes[2].probability,.25)
        self.assertGreater(expected_strokes(stressed),expected_strokes(plan))

    def test_stress_shift_cannot_create_negative_probability(self):
        plan = ShotPlan("A",(Outcome(.02,2),Outcome(.98,4)))
        stressed = shift_error(plan,.1,1)
        self.assertEqual(stressed.outcomes[0].probability,0)
        self.assertAlmostEqual(stressed.outcomes[1].probability,1)

    def test_wide_sensitivity_bands_do_not_claim_proven_positive_ev(self):
        first = ShotPlan("A",(Outcome(.6,2),Outcome(.4,3)))
        second = ShotPlan("B",(Outcome(.65,2),Outcome(.35,3)))
        result = compare_plans(first,second,.1,.4,1)
        self.assertGreater(result["alternative_ev"],0)
        self.assertIsNone(result["robust_preference"])
        self.assertLess(result["ev_low"],0)

    def test_nonfinite_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            expected_strokes(ShotPlan("A",(Outcome(float("nan"),2),Outcome(.5,3))))
        with self.assertRaises(ValueError):
            plan_sensitivity(ShotPlan("A",(Outcome(.5,2),Outcome(.5,3))),float("nan"))

    def test_holed_outcome_has_exactly_zero_remaining_cost(self):
        plan = ShotPlan("Putt",(Outcome(.8,0),Outcome(.2,1)))
        result = plan_sensitivity(plan,0,.25,1)
        self.assertAlmostEqual(result["high"],1.25)
