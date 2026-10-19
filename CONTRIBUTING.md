# Contributing

Use Windows and Python 3.12 or newer with Tcl/Tk installed.

```powershell
.\setup.ps1 -NoShortcuts
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests must stay offline and use synthetic accounts and golf data. Never add real
Garmin exports, real screenshots, credentials, token caches, or private location
data to a commit. Do not add automatic login attempts to tests.

Keep the distinction between:

- GIR versus a tracked approach's on-green finish;
- fairway outcomes versus par-3 tee outcomes;
- stock carry versus recorded shot length including roll;
- wedge approaches versus chips or recovery shots;
- observed frequencies versus assumed probabilities;
- sensitivity ranges versus statistical confidence intervals.
- shared selected-game statistics versus account-wide Garmin aggregates;
- 9-hole versus 18-hole gross scores, and missing tracking versus a recorded zero;
- within-role historical club consistency versus current-shot confidence or EV.
- mutually exclusive score accounting versus causal or additive stroke savings;
- internally consistent coordinate encoding versus verified pins/putting states;
- checked source-bound journal entries versus stale notes after a re-import;
- licensed, population-labeled references versus personal calibration or future EV.

The app must not claim proven positive EV or guaranteed handicap improvement
from a small or incomplete dataset. Never suppress unknown outcomes to improve a
chart. All account-mutating operations are out of scope for this read-only app.
