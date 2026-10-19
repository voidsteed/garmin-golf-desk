import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from golf_app import GolfApp
from golf_data import snapshot_from_exports
from golf_research_ui import ShotReview,VIEWS
from test_golf_baselines import synthetic_reference
from test_golf_ui import fixture


class ResearchUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get("OPENCODE_TEST_TMP"))
        root=Path(self.temp.name)
        self.app=GolfApp(root/"exports",root/"appdata",visible=False)
        self.app.model=snapshot_from_exports([(Path("fixture.json"),fixture())])
        self.errors=[]
        self.app.root.report_callback_exception=lambda kind,value,trace:self.errors.append(kind.__name__)
        self.app.go_research()

    def tearDown(self):
        if self.app.research_view:
            self.app.research_view.remember_form()
        self.app.close()
        self.temp.cleanup()

    def test_all_research_modes_render_with_missing_measurements(self):
        for view in VIEWS:
            self.app.research_view.go(view)
            self.app.root.update_idletasks()
        self.assertEqual(self.errors,[])

    def test_round_and_hole_journal_save_independently_and_do_not_change_source(self):
        self.app.research_view.go("Round journal")
        view=self.app.research_view
        before=copy.deepcopy(self.app.model.rounds)
        view.form_fields["round_putts_status"].set("Verified")
        view.form_fields["hole_first_putt_feet"].set("25")
        view.form_fields["hole_distance_basis"].set("Measured")
        view.save_hole_action()
        self.assertTrue(view.dirty())
        view.save_round_action()
        self.assertFalse(view.dirty())
        note=self.app.research_store.hole_note(self.app.model,"101",1)
        self.assertEqual(note["first_putt_feet"],25)
        self.assertEqual(note["first_putt_bin"],"15–30 ft")
        self.assertEqual(self.app.model.rounds,before)

    def test_unsaved_journal_is_not_discarded_without_confirmation(self):
        self.app.research_view.go("Round journal")
        self.app.research_view.form_fields["hole_note"].set("Unsaved synthetic note")
        with patch("golf_research_ui.messagebox.askyesno",return_value=False):
            self.app.show_page("overview")
        self.assertEqual(self.app.page,"improve")
        self.assertTrue(self.app.research_view.dirty())

    def test_confirmed_discard_restores_the_form_instead_of_marking_it_saved(self):
        self.app.research_view.go("Round journal")
        view=self.app.research_view
        view.form_fields["hole_note"].set("Unsaved synthetic note")
        with patch("golf_research_ui.messagebox.askyesno",return_value=True):
            self.assertTrue(view.can_leave())
        self.assertEqual(view.form_fields["hole_note"].get(),"")
        self.assertEqual(self.app.research_store.hole_note(self.app.model,"101",1),{})

    def test_reference_workbench_exposes_tee_and_chip_state_review(self):
        from test_golf_game import model_fixture
        self.app.model=model_fixture()
        self.app.go_research("Strokes-gained reference")
        roles={r["role"] for r in self.app.research_view.reference_shot_records}
        self.assertTrue({"TEE","CHIP","APPROACH","RECOVERY"}.issubset(roles))

    def test_destroyed_research_labels_do_not_leave_broken_resize_callbacks(self):
        for _ in range(3):
            for view in VIEWS:
                self.app.research_view.go(view)
                self.app.root.update()
        self.assertEqual(self.errors,[])

    def test_chip_practice_log_is_account_scoped_and_saves_observed_cost(self):
        self.app.research_view.go("Carry & chip practice")
        view=self.app.research_view
        for key,value in {"role":"Chip trial","session":"Matched fringe test","lie":"Short grass","on_green":"Yes","finish_feet":"5","strokes_to_finish":"2"}.items():
            view.form_fields["practice_"+key].set(value)
        view.add_practice_action()
        rows=self.app.research_store.scope(self.app.model)["practice"]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["strokes_to_finish"],2)
        self.assertFalse(view.dirty())

    def test_reference_calculator_uses_supplied_reference_not_synthetic_fallback(self):
        self.app.research_view.go("Strokes-gained reference")
        view=self.app.research_view
        view.calculate_reference_action()
        self.assertIn("Import a valid",view.reference_result_message.get())
        self.app.research_store.save_baseline(self.app.model,synthetic_reference().to_dict())
        view.remember_form()
        view.render()
        for key,value in {"start":"450","start_unit":"feet","start_lie":"Fairway","end":"30","end_unit":"feet","end_lie":"Green","penalty":"0"}.items():
            view.form_fields["calc_"+key].set(value)
        view.calculate_reference_action()
        self.assertIn("+0.20",view.reference_result_message.get())
        self.assertFalse(view.dirty())

    def test_gps_draft_never_verifies_a_green_distance_automatically(self):
        record={"date":"2026-10-01","hole":1,"club":"5 iron","round_id":"101","key":"fake-shot","note":{},"start_proxy":150,"end_proxy":3,"start_lie":"Fairway","end_lie":"Green"}
        dialog=ShotReview(self.app.root,self.app.model,self.app.research_store,record)
        dialog.withdraw()
        dialog.verified.set(True)
        dialog.draft()
        self.assertFalse(dialog.verified.get())
        self.assertEqual(dialog.variables["end_yards"].get(),"")
        dialog.destroy()


if __name__=="__main__":
    unittest.main()
