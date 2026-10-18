import unittest

from golf_data import GolfSnapshot
from golf_strategy import build_shot_plan


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.model = GolfSnapshot(clubs={"1":{"clubTypeId":1},"2":{"clubTypeId":15},"3":{"clubTypeId":23},"4":{"clubTypeId":22}})

    def test_normal_misses_inform_safe_zone_not_a_fake_live_map(self):
        plan = build_shot_plan(self.model,"approach",2,hazard="Right")
        self.assertIn("left-center",plan["aim"])
        self.assertEqual(plan["club"],"6 iron")
        self.assertIn("not a live course map",plan["limit"])

    def test_insufficient_carry_requires_layup_or_another_club(self):
        plan = build_shot_plan(self.model,"tee",1,carry=180,hazard_carry=200)
        self.assertTrue(plan["layup"])
        self.assertIn("Do not attempt",plan["aim"])

    def test_carry_is_not_silently_inferred_from_tracked_total_distance(self):
        plan = build_shot_plan(self.model,"approach",2,target=170)
        self.assertFalse(plan["layup"])
        self.assertTrue(any("does not fill" in x for x in plan["checks"]))

    def test_putting_start_line_follows_user_read_not_old_shot_positions(self):
        plan = build_shot_plan(self.model,"putting",3,putt=35,break_direction="Breaks left")
        self.assertIn("right/high side",plan["aim"])
        self.assertTrue(any("no fixed inches" in x for x in plan["checks"]))

    def test_chip_plan_does_not_treat_a_chip_average_as_full_wedge_carry(self):
        plan = build_shot_plan(self.model,"wedge",4,wedge_role="Greenside chip")
        self.assertIn("landing spot",plan["aim"])
        self.assertIn("lower-running",plan["decision"])

    def test_invalid_distance_is_rejected(self):
        for value in (-10,float("nan"),True,"not a number"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                build_shot_plan(self.model,carry=value)
