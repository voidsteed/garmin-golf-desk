import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from golf_store import SessionStore, SessionStoreError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="golfdesk-store-", dir=os.environ.get("OPENCODE_TEST_TMP"))
        self.root = Path(self.temp.name)
        self.path = self.root / "session.dpapi"

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
    def test_real_windows_encryption_roundtrip_and_forget(self):
        store = SessionStore(self.path)
        self.assertIsNone(store.load())
        tokens = json.dumps({"access_token": "FAKE-TEST-ACCESS", "refresh_token": "FAKE-TEST-REFRESH"})
        store.save("test@example.invalid", tokens)
        raw = self.path.read_bytes()
        self.assertNotIn(b"FAKE-TEST", raw)
        self.assertNotIn(b"test@example.invalid", raw)
        self.assertEqual(store.load(), {"email": "test@example.invalid", "tokens": tokens})
        neighbor = self.root / "unrelated.txt"
        neighbor.write_text("keep", encoding="utf-8")
        store.forget()
        self.assertFalse(self.path.exists())
        self.assertEqual(neighbor.read_text(encoding="utf-8"), "keep")

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
    def test_tampered_encrypted_file_fails_closed(self):
        store = SessionStore(self.path)
        store.save("test@example.invalid", '{"token":"FAKE"}')
        raw = bytearray(self.path.read_bytes())
        raw[-1] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaises(SessionStoreError):
            store.load()

    def test_encryption_failure_never_writes_plaintext(self):
        def broken(_):
            raise SessionStoreError("Protection unavailable")
        store = SessionStore(self.path, encrypt=broken)
        with self.assertRaises(SessionStoreError):
            store.save("test@example.invalid", '{"token":"FAKE"}')
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_atomic_replace_failure_preserves_old_cache(self):
        store = SessionStore(self.path, encrypt=lambda _: b"ENCRYPTED-TEST-BLOB")
        store.save("test@example.invalid", '{"token":"FAKE"}')
        original = self.path.read_bytes()
        with patch("golf_store.os.replace", side_effect=OSError("unavailable")):
            with self.assertRaises(SessionStoreError):
                store.save("other@example.invalid", '{"token":"OTHER"}')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_plain_json_is_not_accepted_as_encrypted_cache(self):
        self.path.write_text('{"password":"DO-NOT-USE"}', encoding="utf-8")
        with self.assertRaises(SessionStoreError):
            SessionStore(self.path).load()


if __name__ == "__main__":
    unittest.main()
