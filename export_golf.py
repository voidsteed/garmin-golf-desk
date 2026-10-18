"""Export golf data without editing records or saving sign-in tokens."""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import logging
import os
import re
import sys
import time
import uuid
import warnings
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Iterator

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

BASE_DIR = Path(__file__).resolve().parent
SENSITIVE_KEYS = frozenset(
    {
        "password", "passwd", "authorization", "cookie", "setcookie",
        "accesstoken", "refreshtoken", "idtoken", "oauthtoken", "oauth1token",
        "oauth2token", "clientsecret", "mfasecret", "mfacode", "csrftoken",
        "email", "emailaddress",
    }
)


class ExportError(Exception):
    """An exporter-generated error message that is safe to display."""


class _StopRequests(Exception):
    """Stop requesting data after an authentication failure or rate limit."""


def read_secret(prompt: str) -> str:
    """Refuse getpass's echoing fallback if a private console is unavailable."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise ExportError(
                "A private password prompt is unavailable. Open Export Golf Stats.cmd "
                "in a normal local Windows window."
            ) from None


@contextlib.contextmanager
def private_session(client_factory: Callable[..., Any] = Garmin) -> Iterator[Any]:
    """Prompt locally and keep this session separate from existing token stores."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ExportError(
            "Sign-in needs a local interactive window. Open Export Golf Stats.cmd; "
            "do not enter a password in a chat or a captured command."
        )

    email = input("Garmin email: ").strip()
    password = read_secret("Garmin password (hidden): ")
    if not email or not password:
        password = None
        raise ExportError("Email and password are required. Nothing was downloaded.")

    old_tokenstore = os.environ.pop("GARMINTOKENS", None)
    api = None
    try:
        try:
            api = client_factory(
                email=email,
                password=password,
                prompt_mfa=lambda: read_secret(
                    "Garmin verification code (hidden; press Enter when done): "
                ).strip(),
                retry_attempts=0,
            )
        finally:
            password = None
        # No tokenstore argument: the library must neither load nor save a cache.
        api.login()
        api.password = None
        yield api
    finally:
        password = None
        if api is not None:
            api.password = None
            # Called while GARMINTOKENS is absent so existing caches are untouched.
            with contextlib.suppress(Exception):
                api.logout()
        if old_tokenstore is not None:
            os.environ["GARMINTOKENS"] = old_tokenstore


def scorecard_list(payload: Any) -> list[dict[str, Any]]:
    """Accept known list/envelope shapes without guessing at unrelated objects."""
    if payload is None:
        return []
    if isinstance(payload, dict):
        if not payload:
            return []
        for key in ("scorecardList", "items", "scorecards", "scorecardSummaries"):
            if key in payload:
                payload = payload[key]
                break
        else:
            if "scorecardId" in payload or "id" in payload:
                payload = [payload]
            else:
                raise ValueError("Unknown scorecard summary format")
    if payload is None:
        return []
    if not isinstance(payload, list) or any(not isinstance(x, dict) for x in payload):
        raise ValueError("Unknown scorecard summary format")
    return payload


def scorecard_id(card: dict[str, Any]) -> str | None:
    """Allow only positive numeric IDs from a scorecard response."""
    value = card.get("scorecardId")
    if value is None:
        value = card.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,24}", text) or int(text) <= 0:
        return None
    return str(int(text))


def problem_for(section: str, exc: Exception) -> dict[str, str]:
    """Do not put third-party exception messages, URLs, or tokens in exports."""
    if isinstance(exc, GarminConnectTooManyRequestsError):
        code, message = "rate_limited", "Garmin rate-limited requests; further reads stopped."
    elif isinstance(exc, GarminConnectAuthenticationError):
        code, message = "authentication", "Garmin stopped accepting the session; further reads stopped."
    elif isinstance(exc, GarminConnectNotFoundError):
        code, message = "unavailable", "This golf section was not available from Garmin."
    elif isinstance(exc, GarminConnectConnectionError):
        code, message = "connection", "This golf section could not be downloaded."
    elif isinstance(exc, (ValueError, TypeError)):
        code, message = "unexpected_response", "Garmin returned an unrecognized golf response."
    else:
        code, message = "request_failed", "This golf request failed; no exception details were saved."
    return {"section": section, "code": code, "message": message}


def collect_golf(
    api: Any,
    rounds: int = 20,
    include_shots: bool = False,
    progress: Callable[[str], None] = print,
    delay_seconds: float = 0.75,
) -> dict[str, Any]:
    """Request only golf reads, with bounded rounds and fail-fast rate limits."""
    if isinstance(rounds, bool) or not isinstance(rounds, int) or not 1 <= rounds <= 100:
        raise ValueError("rounds must be an integer from 1 through 100")
    result: dict[str, Any] = {
        "schema_version": 1,
        "exported_at_utc": datetime.now(UTC).isoformat(),
        "library": f"garminconnect {version('garminconnect')}",
        "source": "Garmin Connect via an unofficial local client",
        "scope": {"round_limit": rounds, "include_shots": include_shots},
        "measurement_system": getattr(api, "unit_system", None),
        "golf": {"user_stats": None, "club_stats": None, "scorecard_summaries": [], "scorecards": []},
        "successful_requests": 0,
        "errors": [],
        "stopped_early": False,
    }
    requests_started = 0

    def fetch(section: str, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        nonlocal requests_started
        if requests_started and delay_seconds > 0:
            time.sleep(delay_seconds)
        requests_started += 1
        progress(f"Reading {section}...")
        try:
            data = method(*args, **kwargs)
        except Exception as exc:
            problem = problem_for(section, exc)
            result["errors"].append(problem)
            progress(f"  {problem['message']}")
            if isinstance(exc, (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError)):
                result["stopped_early"] = True
                raise _StopRequests from None
            return None
        result["successful_requests"] += 1
        return data

    try:
        result["golf"]["user_stats"] = fetch("overall golf stats", api.get_golf_user_stats)
        result["golf"]["club_stats"] = fetch("club stats", api.get_golf_club_stats)
        summary = fetch("recent round summaries", api.get_golf_summary, start=0, limit=rounds)
        try:
            cards = scorecard_list(summary)[:rounds]
        except (ValueError, TypeError) as exc:
            result["errors"].append(problem_for("recent round summaries", exc))
            cards = []
        result["golf"]["scorecard_summaries"] = cards

        seen: set[str] = set()
        for index, card in enumerate(cards, 1):
            card_id = scorecard_id(card)
            if card_id is None:
                result["errors"].append({
                    "section": f"scorecard {index}",
                    "code": "invalid_id",
                    "message": "This summary had no usable scorecard ID; its details were skipped.",
                })
                continue
            if card_id in seen:
                continue
            seen.add(card_id)
            entry: dict[str, Any] = {"scorecard_id": card_id, "detail": None}
            result["golf"]["scorecards"].append(entry)
            entry["detail"] = fetch(f"scorecard {index}/{len(cards)}", api.get_golf_scorecard, card_id)
            if include_shots:
                entry["shots"] = fetch(f"shots {index}/{len(cards)}", api.get_golf_shot_data, card_id)
    except _StopRequests:
        pass

    result["status"] = "partial" if result["errors"] else "complete"
    return result


def redact_secrets(value: Any) -> Any:
    """Defensively remove credential-shaped fields and email addresses by key."""
    if isinstance(value, dict):
        return {
            str(key): redact_secrets(item)
            for key, item in value.items()
            if re.sub(r"[^a-z0-9]", "", str(key).lower()) not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def save_export(data: dict[str, Any], output_dir: Path) -> Path:
    """Write a fresh JSON file; never overwrite a previous export."""
    text = json.dumps(redact_secrets(data), ensure_ascii=False, indent=2, allow_nan=False)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"garmin-golf-{stamp}-{uuid.uuid4().hex[:8]}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
    except BaseException:
        # O_EXCL guarantees this is our newly created file, not existing work.
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return path


def round_count(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Choose a round count from 1 through 100.") from None
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("Choose a round count from 1 through 100.")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=round_count, default=20, help="Recent rounds to request (1-100; default: 20).")
    parser.add_argument("--include-shots", action="store_true", help="Also export detailed shots, which may include GPS positions.")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "exports", help="Folder for new JSON exports.")
    args = parser.parse_args(argv)

    # Do not let third-party debug/error logging expose authentication details.
    logging.disable(logging.CRITICAL)
    print("Garmin Golf - Private Local Export")
    print("Unofficial client. Golf reads only; no edits or uploads.")
    print("Enter credentials only in this window. Password/code typing is hidden.")
    print("No sign-in token cache is loaded or saved. Ctrl+C cancels.")
    print(f"Scope: up to {args.rounds} recent rounds, overall stats, and club stats.")
    if args.include_shots:
        print("Detailed shots ENABLED: the export may include shot GPS positions.")
    else:
        print("Detailed shot/GPS export is off.")
    print()

    try:
        with private_session() as api:
            print("Signed in. Downloading golf data...")
            data = collect_golf(api, args.rounds, args.include_shots)
        if not data["successful_requests"]:
            print("No golf data could be downloaded. Nothing was saved.")
            return 2
        path = save_export(data, args.output_dir.resolve())
        count = len(data["golf"]["scorecard_summaries"])
        print(f"\nExport saved ({data['status']}; {count} round summaries):")
        print(path)
        if not count:
            print("No scorecards were returned. Sync your watch and check Garmin Golf.")
        if data["errors"]:
            print("Some sections were unavailable. Safe descriptions are in the JSON errors field.")
        print("The export contains private golf data. Do not share it publicly.")
        return 0
    except KeyboardInterrupt:
        print("\nCanceled. No new export was saved.")
        return 130
    except ExportError as exc:
        print(f"\n{exc}")
    except GarminConnectTooManyRequestsError:
        print("\nGarmin rate-limited sign-in. Stop and try again later; do not keep retrying.")
    except GarminConnectAuthenticationError:
        print("\nGarmin could not complete sign-in. Check your login on Garmin's official website.")
    except GarminConnectConnectionError:
        print("\nCould not complete Garmin sign-in. Its service or your connection may be unavailable.")
    except OSError:
        print("\nThe export could not be read or saved. Check the folder's permissions and free space.")
    except Exception:
        print("\nThe exporter could not finish. No exception details were printed to protect sign-in data.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
