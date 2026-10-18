"""Windows-user-bound encryption for optional remembered Garmin sessions."""

from __future__ import annotations

import ctypes
import json
import os
import uuid
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

MAGIC = b"GOLFDESK\x00\x01"
ENTROPY = b"GolfDesk.Garmin.Session.v1"


class SessionStoreError(Exception):
    """A safe, non-secret-bearing storage error."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise SessionStoreError("Remembered sign-in requires Windows user encryption.")
    source_buffer = ctypes.create_string_buffer(data)
    entropy_buffer = ctypes.create_string_buffer(ENTROPY)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    entropy = _Blob(len(ENTROPY), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        second = None
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        second = "Golf Desk remembered Garmin session"
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # CRYPTPROTECT_UI_FORBIDDEN, and deliberately no LOCAL_MACHINE flag.
    if not function(ctypes.byref(source), second, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise SessionStoreError("Windows could not unlock or protect the saved sign-in for this user.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    return _windows_crypt(data)


def unprotect(data: bytes) -> bytes:
    return _windows_crypt(data, decrypt=True)


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / "GolfDesk" if base else Path.home() / "AppData" / "Local" / "GolfDesk"


class SessionStore:
    """Only encrypted bytes are written, including temporary replacement files."""

    def __init__(self, path: Path | None = None, encrypt: Callable[[bytes], bytes] = protect, decrypt: Callable[[bytes], bytes] = unprotect):
        self.path = path if path is not None else app_data_dir() / "garmin-session.dpapi"
        self.encrypt = encrypt
        self.decrypt = decrypt

    @property
    def exists(self) -> bool:
        return self.path.is_file() and not self.path.is_symlink()

    def save(self, email: str, tokens: str) -> None:
        try:
            if not isinstance(email, str) or not isinstance(tokens, str) or not isinstance(json.loads(tokens), dict):
                raise ValueError
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise ValueError
            payload = json.dumps({"version": 1, "email": email, "saved_at": datetime.now(UTC).isoformat(), "tokens": tokens}).encode("utf-8")
            encrypted = MAGIC + self.encrypt(payload)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(encrypted)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("The sign-in could not be remembered securely. No plaintext fallback was used.") from None

    def load(self) -> dict[str, str] | None:
        if not self.path.exists():
            return None
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 512_000:
                raise ValueError
            raw = self.path.read_bytes()
            if not raw.startswith(MAGIC):
                raise ValueError
            data = json.loads(self.decrypt(raw[len(MAGIC):]).decode("utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("email"), str) or not isinstance(data.get("tokens"), str) or not isinstance(json.loads(data["tokens"]), dict):
                raise ValueError
            return {"email": data["email"], "tokens": data["tokens"]}
        except SessionStoreError:
            raise
        except Exception:
            raise SessionStoreError("The remembered sign-in cannot be opened. Please sign in again in the app.") from None

    def forget(self) -> None:
        try:
            # Only this app's single cache file, never a user's other Garmin files.
            self.path.unlink(missing_ok=True)
        except OSError:
            raise SessionStoreError("The saved sign-in could not be removed. Check this app's local-data permissions.") from None
