# Golf Desk — your local Garmin golf dashboard

A Windows desktop app and optional golf-only exporter using the **unofficial**
[python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library.
This is not a Garmin-supported integration.

## Install for your own account

Windows 10/11 and **Python 3.12+ with Tcl/Tk** are required. Each person uses
their own Garmin account; no account, API key, or private player export is
included in this repository. The desktop GUI uses Tkinter/ttk, not Qt.

```powershell
git clone https://github.com/voidsteed/garmin-golf-desk.git
cd garmin-golf-desk
.\setup.ps1 -Launch
```

Setup uses an isolated virtual environment and creates per-user desktop and
Start-menu shortcuts. It does not require an administrator account or change
Windows execution policy. If your policy does not allow the setup script, use
your organization's approved procedure or the manual installation below.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\golf-desk.exe
```

The project is MIT licensed. Garmin names and data formats belong to their
respective owners; this project is not affiliated with Garmin.

## Open the desktop app

Open **Golf Desk** from the desktop shortcut or the Start menu. There is no
console window. Your existing exports load automatically, without signing in.

- **Overview:** scoring trend, handicap, greens, putting, and recent rounds.
- **Improve my game:** visual current-versus-goal practice bars, approach misses
  by named club, an aggregate miss-direction diagram, and a colored chart of
  costly holes. Choose the latest three or all imported full rounds. Practice
  goals are starter targets, not strokes-gained estimates; categories overlap.
- **Course strategy:** a schematic target-zone guide for tee shots, approaches,
  wedges/chips, and putting. Enter current trouble, distances, reliable carry,
  lie/wind conditions and your green read. It does not invent a live hole map,
  exact break, or an optimal aim coordinate.
- **Expected score / EV:** compare two shot plans using mutually exclusive
  outcome probabilities, immediate penalties, and expected strokes remaining.
  Positive EV means lower expected strokes than the alternative. Human-error
  stress tests and remaining-stroke uncertainty are explicit assumptions, not
  statistical confidence intervals. FIR/GIR alone are not the objective.
- **Latest 3 rounds:** comparison, hole-by-hole scorecards, penalties, and
  detailed-shot coverage.
- **Approach clubs:** recent approach outcomes by club, individual shot logs,
  and a separate view for Garmin's aggregate club statistics. Unknown outcomes
  and unassigned clubs are shown explicitly, not treated as successful shots.
- **Data & privacy:** remembered sign-in controls, local export history, and
  important accuracy/privacy limits.
- **Tee & short game:** separate tee/driver, putting, and wedge tabs with charts
  and exportable tables. Fairway accuracy is not mixed with par-3 green accuracy;
  multiple-tee holes are excluded from ambiguous club attribution. Putting uses
  scorecards, not incomplete auto-detected putt lists. Wedge approaches, chips,
  and other shots are kept separate; measured shot length is not carry distance.

Use **Update from Garmin** to sign in and choose how many rounds to import.
Detailed shots and locations are optional. Use **Get latest 3 shot details** for
the focused three-round approach analysis. Passwords and verification codes are
entered in masked dialogs inside the app, not in a chat or console.

Personal exports, local club names, and the encrypted session are stored under
`%LOCALAPPDATA%\GolfDesk`, outside the source repository. The GUI uses
`%LOCALAPPDATA%\GolfDesk\exports`; the optional console exporter still uses its
own `exports` folder unless you choose another output directory.

### EV honesty and human error

The current shot history is not automatically a calibrated model of a specific
target, distance, wind, lie, pin, pressure level or player's error distribution.
The EV tool therefore starts blank. The worked example is explicitly marked as
illustrative, not your personal probabilities. Enter estimates appropriate to
the situation, and do not double-count normal misses, mishits, recoveries or
penalties as overlapping probability categories.

`Expected strokes = 1 current stroke + Σ P(outcome) × (immediate penalty + expected remaining strokes)`

The calculator shows nominal estimates and sensitivity bands. Overlapping bands
do not establish a robust preference. Even a stable result under those assumed
bounds does not validate the probabilities or guarantee positive EV, a lower
score, or a handicap reduction. Better calibration needs complete contextual
shot data and defensible expected-strokes baselines. Read [SECURITY.md](SECURITY.md)
before sharing any diagnostics or personal data.

### Remember this PC

Leave **Remember this PC** checked to save an encrypted session, not your
password. Windows DPAPI protects the tokens for the current Windows user. Only
encrypted bytes are written, including temporary replacement files. Sessions
are stored under `%LOCALAPPDATA%\GolfDesk\garmin-session.dpapi`, outside the
exports folder. No plaintext library token cache is used.

The app refreshes an accepted session on later updates. Garmin can expire or
revoke it, so six months without another sign-in **cannot be guaranteed**.
The first app sign-in is still needed because earlier console exports did not
save a session. Unchecking remember after a successful sign-in removes the app's
cache. **Data & privacy → Forget sign-in on this PC** removes only that encrypted
cache, leaving golf exports intact. Forgetting locally does not revoke an
already issued token at Garmin.

DPAPI is Windows-user protection, not isolation from other programs running as
the same Windows user. Never share the encrypted cache or decrypted tokens.

### Club labels and data coverage

Club names are automatic, even when Garmin's online catalog is unavailable.
The app includes the standard mappings from Garmin's DI-GOLF `CLUB_TYPES` v1
catalog: for example, type 13 is **4 iron**, type 15 is **6 iron**, and type 17 is
**8 iron**. The static reference catalog is published
[here](https://github.com/torjussa/golf-analytics/blob/main/data/DI-GOLF/Golf-CLUB_TYPES.json).
No player data from that repository is used.

Your Garmin custom club names and local display-name overrides take precedence.
**Edit club display name** is optional and does not edit Garmin records.
Unassigned club ID 0 remains **Unassigned club**, and truly unrecognized future
types are not assigned a made-up iron or wood name.

Recent shot outcomes use Garmin's `APPROACH` classification and recorded end
lies. Green finishes are not the same as GIR or strokes gained. Missing holes,
unknown outcomes, and small samples remain visible. Aggregate club percentages
are not restricted to the latest three rounds, and `shotsCount` is not an
approach-attempt denominator. Recorded shot length is not carry distance.

Exports are combined only when their player profile IDs match. Data from
different or unidentified accounts is not silently combined.

## Optional console exporter

Double-click **Export Golf Stats.cmd**. Enter your Garmin email, password, and
any verification code in that separate window, **not in a chat**. Passwords and
verification codes are hidden while you type. Press Enter after each entry.

The default export includes:

- Overall golf statistics, when available for the account.
- Club statistics.
- Summaries and scorecard details for up to 20 recent rounds returned by Garmin.

The resulting JSON file is saved in the `exports` folder. Each run creates a new
file rather than overwriting previous exports. An export may be partial if
Garmin does not provide a particular section; check its `errors` field.

Sync your watch with Garmin Connect or Garmin Golf first if recent rounds are
missing. A USB connection to the watch is not needed for this cloud export.

## Privacy and limits

- Passwords and verification codes are sent to Garmin's HTTPS sign-in service by
  the locally running third-party library. They are not requested in chat,
  printed, or saved by either the desktop app or console exporter.
- The **console** exporter disables the library's token-store environment setting for its
  own process, does not load existing saved sessions, and does not save sign-in
  tokens. You must sign in each console run. The desktop app's explicit remember
  option uses a separate DPAPI-encrypted cache, described above. This does not revoke a session at Garmin
  or guarantee that secrets can be erased from operating-system memory.
- After signing in, the exporter calls only the five golf read methods. Sign-in
  itself also retrieves the profile/settings needed by the library. Those
  profile/settings responses are not exported.
- Club-type labels resolve from the bundled standard catalog, imported catalog
  labels, or custom names. Sync does not depend on an unavailable online
  club-type-label endpoint.
- The script has no upload, edit, or delete operations. The sign-in token itself
  is **not** a read-only-scoped token, so using this tool still requires trusting
  the third-party library and its dependencies with account access.
- Exports contain private golf data, potentially including course names, round
  dates, and location-related metadata. Anyone with access to the files can read
  them. Do not upload the entire project folder or share exports publicly.
- Detailed shot exports are **off by default** because they may include GPS
  positions. They can be explicitly enabled with the option below.
- Golf coverage depends on the data Garmin has recorded, your account, and its
  current service behavior. The tool has offline tests, but a successful export
  from a new account cannot be confirmed until you sign in.
- This unofficial integration can stop working. If Garmin blocks sign-in or
  rate-limits requests, stop and use its official website instead of repeatedly
  attempting to sign in.

## Optional command-line settings

Run these commands in a local terminal, not in a chat. Do not put a password in
the command line or an environment variable.

```bat
.venv\Scripts\python.exe -I export_golf.py --help
.venv\Scripts\python.exe -I export_golf.py --rounds 50
.venv\Scripts\python.exe -I export_golf.py --rounds 20 --include-shots
```

`--rounds` accepts 1 through 100. Requests are paced, and authentication failures
or rate limits stop further data requests while preserving any partial results.

For just the latest three rounds with detailed shots, double-click
**Export Latest 3 Rounds.cmd**. This explicitly includes shot locations and may
require another private sign-in because credentials and tokens are not saved.

## Setup and offline checks

Requires Python 3.12 or later. Dependencies are isolated in `.venv`; no system
Python packages need to be changed.

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests use fake responses and do not sign in to Garmin or access an account.
They cover Windows encryption, corrupted-cache rejection, saved-session reuse,
secret cleanup, data/account separation, missing approach outcomes, and UI
navigation and masked sign-in dialogs. No additional GUI dependency is needed;
the app uses Python's Windows Tk toolkit.
`requirements.lock.txt` records the dependency versions installed during setup;
`requirements.txt` pins just the main library for a fresh dependency resolution.
