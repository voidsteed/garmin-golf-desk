"""Background sync service used by the desktop UI; no console prompts."""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError, GarminConnectTooManyRequestsError

from export_golf import collect_golf, save_export
from golf_store import SessionStore, SessionStoreError


class SyncCancelled(BaseException):
    """Not swallowed by the exporter's recoverable request-error handling."""


class SignInRequired(Exception):
    def __init__(self, email: str = ""):
        super().__init__("Please sign in again in the app.")
        self.email = email


class SyncError(Exception):
    """An intentionally generic message, never a raw authentication error."""


@dataclass
class SyncResult:
    path: Path
    data: dict[str, Any]
    remembered: bool
    warnings: list[str] = field(default_factory=list)


def sync_golf(
    output_dir: Path,
    rounds: int,
    include_shots: bool,
    credentials: dict[str, str] | None,
    remember: bool,
    prompt_mfa: Callable[[], str],
    progress: Callable[[str], None],
    cancel: threading.Event,
    store: SessionStore | None = None,
    client_factory: Callable[..., Any] = Garmin,
    collector: Callable[..., dict[str, Any]] = collect_golf,
) -> SyncResult:
    """Use an encrypted saved session or UI-supplied credentials for one sync."""
    logging.disable(logging.CRITICAL)
    store = store if store is not None else SessionStore()
    api = None
    email = ""
    password = None
    remembered = False
    messages: list[str] = []
    previous = os.environ.pop("GARMINTOKENS", None)

    def check_cancel() -> None:
        if cancel.is_set():
            raise SyncCancelled

    def report(message: str) -> None:
        check_cancel()
        progress(message)

    def persist() -> None:
        nonlocal remembered
        if not remember:
            return
        try:
            store.save(email, api.client.dumps())
            remembered = True
        except SessionStoreError:
            remembered = False
            text = "Golf data is available, but Windows could not remember this sign-in securely. Sign in again next time."
            if text not in messages:
                messages.append(text)

    try:
        check_cancel()
        if credentials is not None:
            email = credentials.pop("email", "").strip()
            password = credentials.pop("password", "")
            credentials.clear()
            if not email or not password:
                raise SyncError("Enter your Garmin email and password in the app.")
            report("Signing in securely with Garmin…")
            try:
                api = client_factory(email=email, password=password, prompt_mfa=prompt_mfa, retry_attempts=0)
            finally:
                password = None
            api.login()
        else:
            report("Opening your Windows-protected sign-in…")
            try:
                saved = store.load()
            except SessionStoreError:
                raise SignInRequired from None
            if not saved:
                raise SignInRequired
            email = saved["email"]
            api = client_factory(prompt_mfa=prompt_mfa, retry_attempts=0)
            try:
                # Inline JSON is held only in memory. No plaintext tokenstore path.
                api.login(tokenstore=saved.pop("tokens"))
            except GarminConnectAuthenticationError:
                raise SignInRequired(email) from None
            finally:
                saved.clear()
        api.password = None
        check_cancel()
        if remember:
            persist()
        else:
            # The UI explicitly explains that unchecking remember removes its cache.
            store.forget()
        report("Connected. Reading golf data only…")
        data = collector(api, rounds=rounds, include_shots=include_shots, progress=report)
        check_cancel()
        if not data.get("successful_requests"):
            raise SyncError("Garmin did not return golf data. Nothing new was saved. Try its official website before retrying.")
        path = save_export(data, output_dir)
        auth_failed = any(x.get("code") == "authentication" for x in data.get("errors", []))
        if not auth_failed:
            persist()
        return SyncResult(path, data, remembered, messages)
    except SyncCancelled:
        raise
    except (SignInRequired, SyncError):
        raise
    except GarminConnectTooManyRequestsError:
        raise SyncError("Garmin rate-limited access. Please wait before trying again; do not repeatedly sign in.") from None
    except GarminConnectAuthenticationError:
        raise SyncError("Garmin did not accept the sign-in or verification code. Check your account on Garmin's official website.") from None
    except GarminConnectConnectionError:
        raise SyncError("Could not reach Garmin or complete sign-in. This unofficial integration may be temporarily unavailable.") from None
    except SessionStoreError:
        raise SyncError("Windows could not update this app's remembered sign-in. No plaintext credentials were saved.") from None
    except Exception:
        raise SyncError("The update could not finish. Your Garmin records were not changed; sensitive error details were not logged.") from None
    finally:
        password = None
        if credentials is not None:
            credentials.clear()
        if api is not None:
            api.password = None
            with contextlib.suppress(Exception):
                api.logout()
        if previous is not None:
            os.environ["GARMINTOKENS"] = previous
