import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from golf_data import GolfSnapshot
from golf_research_store import ResearchStore,ResearchStoreError
from test_golf_game import model_fixture


class JournalStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP"))
        self.path=Path(self.temp.name)/"research-notes.json"
        self.store=ResearchStore(self.path)
        self.a=model_fixture()
        self.a.account_identities=frozenset({"a"})
        self.b=GolfSnapshot(account_identities=frozenset({"b"}),clubs={"10":{"clubTypeId":15}})

    def tearDown(self):
        self.temp.cleanup()

    def test_hole_notes_are_private_account_scoped_and_roundtrip(self):
        self.store.save_hole(self.a,"round",1,{"first_putt_feet":25,"distance_basis":"Measured","penalty_phase":"Approach"})
        note=ResearchStore(self.path).hole_note(self.a,"round",1)
        self.assertEqual(note["first_putt_bin"],"15–30 ft")
        self.assertEqual(note["first_putt_feet"],25)
        self.assertEqual(self.store.hole_note(self.b,"round",1),{})

    def test_exact_distance_requires_a_basis(self):
        with self.assertRaises(ValueError):
            self.store.save_hole(self.a,"r",1,{"first_putt_feet":10})
        self.assertFalse(self.path.exists())

    def test_invalid_or_nonfinite_values_are_not_saved(self):
        for value in (-1,float("nan"),True,"wrong"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.store.save_hole(self.a,"r",1,{"first_putt_feet":value,"distance_basis":"Measured"})

    def test_verified_shot_states_require_complete_information(self):
        with self.assertRaises(ValueError):
            self.store.save_shot(self.a,"r","s",{"states_verified":True,"start_yards":150})
        with self.assertRaises(ValueError):
            self.store.save_shot(self.a,"r","s",{"end_yards":0})
        self.store.save_shot(self.a,"1","1",{"states_verified":True,"start_yards":100,"start_lie":"Fairway","holed":True})
        self.assertEqual(self.store.shot_note(self.a,"1","1")["end_yards"],0)

    def test_corrupt_existing_file_is_not_overwritten(self):
        original='{"version":1,"accounts":{"broken":"not a collection"}}'
        self.path.write_text(original,encoding="utf-8")
        store=ResearchStore(self.path)
        self.assertIsNotNone(store.error)
        with self.assertRaises(ResearchStoreError):
            store.save_round(self.a,"r",{})
        self.assertEqual(self.path.read_text(encoding="utf-8"),original)

    def test_atomic_failure_preserves_previous_file_and_memory(self):
        self.store.save_round(self.a,"r",{"putts_status":"Verified"})
        previous=self.path.read_bytes()
        with patch("golf_research_store.os.replace",side_effect=OSError("not writable")):
            with self.assertRaises(ResearchStoreError):
                self.store.save_round(self.a,"r",{"putts_status":"Needs correction"})
        self.assertEqual(self.path.read_bytes(),previous)
        self.assertEqual(self.store.round_note(self.a,"r")["putts_status"],"Verified")
        self.assertEqual(list(self.path.parent.glob("*.tmp")),[])

    def test_account_keys_do_not_collide_for_separator_characters(self):
        a=GolfSnapshot(account_identities=frozenset({"a|b"}))
        b=GolfSnapshot(account_identities=frozenset({"a","b"}))
        self.store.save_round(a,"r",{"putts_status":"Verified"})
        self.assertEqual(self.store.round_note(b,"r"),{})

    def test_changed_source_counts_invalidate_only_affected_reviews(self):
        self.store.save_round(self.a,"1",{"putts_status":"Verified","penalties_status":"Verified"})
        self.assertEqual(self.store.round_note(self.a,"1")["putts_status"],"Verified")
        self.a.rounds[0]["holes"][0]["putts"]+=1
        note=self.store.round_note(self.a,"1")
        self.assertEqual(note["putts_status"],"Unchecked")
        self.assertEqual(note["penalties_status"],"Verified")

    def test_another_window_cannot_silently_overwrite_newer_notes(self):
        second=ResearchStore(self.path)
        self.store.save_round(self.a,"1",{"putts_status":"Verified"})
        previous=self.path.read_bytes()
        with self.assertRaisesRegex(ResearchStoreError,"another window"):
            second.save_round(self.a,"1",{"putts_status":"Needs correction"})
        self.assertEqual(self.path.read_bytes(),previous)

    def test_malformed_saved_shot_numbers_fail_closed(self):
        self.path.write_text('{"version":1,"accounts":{"a":{"shots":{"r":{"s":{"start_yards":"150","states_verified":true}}}}}}',encoding="utf-8")
        self.assertIsNotNone(ResearchStore(self.path).error)

    def test_practice_requires_measured_carry_and_matched_session(self):
        with self.assertRaises(ValueError):
            self.store.add_practice(self.a,{"club_id":"10","role":"Full swing","session":"A"})
        with self.assertRaises(ValueError):
            self.store.add_practice(self.a,{"club_id":"10","role":"Full swing","carry_yards":150})
        with self.assertRaises(ValueError):
            self.store.add_practice(self.a,{"club_id":"10","role":"Chip trial","session":"A"})
        key=self.store.add_practice(self.a,{"club_id":"10","role":"Full swing","carry_yards":150,"lateral_yards":-10,"session":"A","contact":"Mishit"})
        self.assertEqual(len(self.store.scope(self.a)["practice"]),1)
        self.store.delete_practice(self.b,key)
        self.assertEqual(len(self.store.scope(self.a)["practice"]),1)
        self.store.delete_practice(self.a,key)
        self.assertEqual(self.store.scope(self.a)["practice"],[])


if __name__=="__main__":
    unittest.main()
