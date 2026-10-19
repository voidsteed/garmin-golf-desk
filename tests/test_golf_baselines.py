import os
import tempfile
import unittest
from pathlib import Path

from golf_baselines import StrokeReference


def synthetic_reference():
    return StrokeReference("Synthetic test reference","Test population","Synthetic fixture, not player data",(("Fairway",50,2.5),("Fairway",150,3.2),("Green",1,1.1),("Green",10,2.0)))


class ReferenceTests(unittest.TestCase):
    def test_interpolation_is_lie_specific_and_not_extrapolated(self):
        reference=synthetic_reference()
        reference.validate()
        self.assertAlmostEqual(reference.lookup(100,"Fairway"),2.85)
        with self.assertRaises(ValueError):
            reference.lookup(200,"Fairway")
        with self.assertRaises(ValueError):
            reference.lookup(100,"Rough")

    def test_holed_state_is_explicit_and_not_a_zero_distance_interpolation(self):
        reference=synthetic_reference()
        self.assertEqual(reference.lookup(None,"Unknown",holed=True),0)
        with self.assertRaises(ValueError):
            reference.lookup(0,"Green")

    def test_current_stroke_and_immediate_penalty_are_counted_once(self):
        self.assertAlmostEqual(synthetic_reference().shot_value(150,"Fairway",10,"Green",0),.2)
        self.assertAlmostEqual(synthetic_reference().shot_value(150,"Fairway",10,"Green",1),-.8)

    def test_csv_requires_permission_provenance_and_correct_units(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP")) as tmp:
            path=Path(tmp)/"reference.csv"
            path.write_text("lie,distance_yards,expected_strokes\nGreen,1,1.1\nGreen,10,2.0\n",encoding="utf-8")
            with self.assertRaises(ValueError):
                StrokeReference.from_csv(path,"Test","Test","Synthetic fixture")
            with self.assertRaises(ValueError):
                StrokeReference.from_csv(path,"Test","Test","",True)
            reference=StrokeReference.from_csv(path,"Test","Test","Synthetic fixture",True)
            self.assertEqual(reference.lookup(10,"Green"),2)

    def test_nonmonotone_duplicate_or_single_point_lies_rejected(self):
        for points in ((("Green",1,1.1),),(("Green",1,1.1),("Green",1,1.2)),(("Green",1,2),("Green",2,1.5))):
            with self.subTest(points=points),self.assertRaises(ValueError):
                StrokeReference("Test","Test","Synthetic",points).validate()

    def test_saved_reference_is_validated_without_fabricated_fallback(self):
        reference=synthetic_reference()
        restored=StrokeReference.from_dict(reference.to_dict())
        self.assertEqual(restored.lookup(150,"Fairway"),3.2)
        self.assertIsNone(StrokeReference.from_dict(None))
        with self.assertRaises(ValueError):
            StrokeReference.from_dict({"name":"Bad","source":"Synthetic","points":[["Green",1,float("nan")],["Green",2,2]]})


if __name__=="__main__":
    unittest.main()
