import os
import tempfile
import unittest
from pathlib import Path

from golf_app import GolfApp, MfaDialog, SyncDialog
from golf_data import snapshot_from_exports


def fixture():
    holes = [{"number": n, "strokes": 5, "putts": 2, "penalties": 0} for n in range(1, 19)]
    return {"exported_at_utc": "2026-10-01", "golf": {
        "user_stats": {"handicap": 14},
        "club_stats": [{"id": 20, "clubTypeId": 14, "clubStats": {"percentGreenHit": 25, "percentGreenMissShort": 50, "shotsCount": 1000}}],
        "scorecard_summaries": [{"id": 101, "playerProfileId": 1, "startTime": "2026-10-01", "courseName": "Test course", "holesCompleted": 18, "strokes": 90, "holePars": "4" * 18, "holes": holes}],
        "scorecards": [{"scorecard_id": "101", "detail": {"scorecardDetails": [{"scorecard": {"id": 101, "playerProfileId": 1, "holesCompleted": 18, "strokes": 90, "holes": holes}, "scorecardStats": {"round": {"greensInRegulation": 6, "greensRecorded": 18, "fairwaysHit": 5, "fairwaysRecorded": 14, "putts": 36}}}]},
                        "shots": {"holeShots": [{"holeNumber": 1, "shots": [{"clubId": 20, "shotType": "APPROACH", "endLoc": {"lie": "Green"}, "meters": 100}]}]}}]}, "errors": []}


class UiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="golfdesk-ui-", dir=os.environ.get("OPENCODE_TEST_TMP"))
        folder = Path(self.temp.name)
        self.app = GolfApp(folder / "exports", folder / "appdata", visible=False)
        self.errors = []
        self.app.root.report_callback_exception = lambda kind, value, trace: self.errors.append(kind.__name__)

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def test_empty_dashboard_and_all_navigation_pages(self):
        for page in ("overview", "improve", "rounds", "clubs", "game", "privacy"):
            self.app.show_page(page)
            self.app.root.update_idletasks()
            self.assertEqual(self.app.page, page)
        self.assertEqual(self.errors, [])

    def test_populated_dashboard_rounds_approaches_and_aggregates_render(self):
        self.app.model = snapshot_from_exports([(Path("fixture.json"), fixture())])
        for page in ("overview", "improve", "rounds", "clubs", "game", "privacy"):
            self.app.show_page(page)
            self.app.root.update_idletasks()
        self.app.approach_mode = "Garmin aggregate club stats"
        self.app.show_page("clubs")
        self.app.root.update_idletasks()
        for tab in ("tee","putting","wedges"):
            self.app.game_tab = tab
            self.app.show_page("game")
            self.app.root.update_idletasks()
        for tab in ("strategy","ev"):
            self.app.improve_tab = tab
            self.app.show_page("improve")
            self.app.root.update_idletasks()
        self.assertEqual(self.errors, [])

    def test_strategy_phases_and_explicit_ev_example_render_without_login(self):
        self.app.model = snapshot_from_exports([(Path("fixture.json"), fixture())])
        self.app.improve_tab = "strategy"
        self.app.show_page("improve")
        for phase in ("tee","approach","wedge","putting"):
            self.app.strategy_view.vars["phase"].set(phase)
            self.app.strategy_view.fields()
            self.app.root.update_idletasks()
            self.assertIsNotNone(self.app.strategy_view.plan)
        self.app.improve_tab = "ev"
        self.app.show_page("improve")
        self.app.ev_view.load_example()
        self.assertTrue(self.app.ev_view.example)
        self.app.ev_view.clear()
        self.assertFalse(self.app.ev_view.example)
        self.assertEqual(self.errors, [])

    def test_signin_dialog_masks_password_and_defaults_to_remember(self):
        dialog = SyncDialog(self.app.root, rounds=3, shots=True)
        dialog.withdraw()
        self.assertTrue(dialog.password_entry.cget("show"))
        self.assertTrue(dialog.remember.get())
        self.assertEqual(dialog.scope.get(), "3")
        self.assertTrue(dialog.shots.get())
        dialog.password.set("FAKE-TEST-PASSWORD")
        dialog.cancel()
        self.assertEqual(dialog.password.get(), "")
        self.assertIsNone(dialog.result)

    def test_verification_dialog_clears_secret_on_cancel(self):
        dialog = MfaDialog(self.app.root)
        dialog.withdraw()
        dialog.secret.set("FAKE-TEST-CODE")
        dialog.cancel()
        self.assertEqual(dialog.secret.get(), "")
        self.assertIsNone(dialog.result)


if __name__ == "__main__":
    unittest.main()
