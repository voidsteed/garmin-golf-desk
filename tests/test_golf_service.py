import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

from golf_service import SignInRequired, SyncCancelled, SyncError, sync_golf
from golf_store import SessionStoreError


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="golfdesk-service-", dir=os.environ.get("OPENCODE_TEST_TMP"))
        self.api = Mock()
        self.api.client.dumps.return_value = '{"di_token":"FAKE-SESSION"}'
        self.store = Mock()
        self.store.load.return_value = {"email": "test@example.invalid", "tokens": '{"di_token":"FAKE-SAVED"}'}
        self.collector = Mock(return_value={"successful_requests": 1, "golf": {"scorecard_summaries": []}, "errors": [], "status": "complete"})

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, credentials=None, remember=True, **extra):
        return sync_golf(Path(self.temp.name), 3, True, credentials, remember, lambda: "FAKE-CODE", lambda _: None,
                         extra.pop("cancel", threading.Event()), store=self.store, client_factory=Mock(return_value=self.api),
                         collector=self.collector, **extra)

    def test_gui_login_remembers_encrypted_tokens_not_password(self):
        credentials = {"email": "test@example.invalid", "password": "FAKE-PASSWORD"}
        self.api.login.side_effect = lambda **_: self.assertNotIn("GARMINTOKENS", os.environ)
        self.api.logout.side_effect = lambda: self.assertNotIn("GARMINTOKENS", os.environ)
        with patch.dict(os.environ, {"GARMINTOKENS": "EXISTING-USER-CACHE"}):
            result = self.run_sync(credentials)
            self.assertEqual(os.environ["GARMINTOKENS"], "EXISTING-USER-CACHE")
        self.assertTrue(result.remembered)
        self.assertEqual(credentials, {})
        self.assertIsNone(self.api.password)
        self.api.login.assert_called_once_with()
        self.api.client.dump.assert_not_called()
        for call in self.store.save.call_args_list:
            self.assertNotIn("PASSWORD", str(call))
        self.assertNotIn("FAKE-PASSWORD", result.path.read_text(encoding="utf-8"))

    def test_saved_session_is_passed_in_memory_without_plaintext_path(self):
        result = self.run_sync()
        self.assertTrue(result.remembered)
        self.api.login.assert_called_once_with(tokenstore='{"di_token":"FAKE-SAVED"}')
        self.api.client.dump.assert_not_called()

    def test_no_saved_session_requires_ui_signin(self):
        self.store.load.return_value = None
        with self.assertRaises(SignInRequired):
            self.run_sync()
        self.collector.assert_not_called()

    def test_expired_session_requires_signin_without_leaking_error(self):
        self.api.login.side_effect = GarminConnectAuthenticationError("SECRET-ERROR-TOKEN")
        with self.assertRaises(SignInRequired) as result:
            self.run_sync()
        self.assertNotIn("SECRET-ERROR-TOKEN", str(result.exception))
        self.store.save.assert_not_called()

    def test_unchecking_remember_removes_only_app_cache(self):
        result = self.run_sync({"email": "test@example.invalid", "password": "FAKE"}, remember=False)
        self.assertFalse(result.remembered)
        self.store.forget.assert_called_once_with()
        self.store.save.assert_not_called()

    def test_protection_failure_is_reported_without_plaintext_fallback(self):
        self.store.save.side_effect = SessionStoreError("Encryption failed")
        result = self.run_sync({"email": "test@example.invalid", "password": "FAKE"})
        self.assertFalse(result.remembered)
        self.assertTrue(result.warnings)
        self.assertTrue(result.path.exists())
        self.api.client.dump.assert_not_called()

    def test_cancel_before_login_makes_no_requests(self):
        cancel = threading.Event()
        cancel.set()
        credentials = {"email": "test@example.invalid", "password": "FAKE"}
        with self.assertRaises(SyncCancelled):
            self.run_sync(credentials, cancel=cancel)
        self.assertEqual(credentials, {})
        self.api.login.assert_not_called()

    def test_rate_limit_error_is_safe_and_not_retried(self):
        self.api.login.side_effect = GarminConnectTooManyRequestsError("SECRET-TOKEN")
        with self.assertRaises(SyncError) as result:
            self.run_sync({"email": "test@example.invalid", "password": "FAKE"})
        self.assertNotIn("SECRET-TOKEN", str(result.exception))
        self.api.login.assert_called_once()


if __name__ == "__main__":
    unittest.main()
