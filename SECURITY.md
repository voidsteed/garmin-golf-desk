# Security and personal data

Golf Desk is an unofficial Garmin client. It is not made or endorsed by Garmin.
Only use an account you own or are authorized to access, and review Garmin's
applicable terms. This app does not bypass account verification or access controls.

- Sign in inside the local desktop app, never in GitHub issues, a chat, source
  code, command-line arguments, or an environment file.
- Remembered sessions use Windows user-bound DPAPI encryption. Passwords and
  verification codes are not saved. Decrypted tokens stay in process memory;
  there is no plaintext token-file fallback.
- DPAPI does not isolate secrets from other programs running as your Windows
  user. A remembered token grants broader account access than this read-only app
  uses. A session's lifetime is controlled by Garmin, not a six-month guarantee.
- The app stores personal files under `%LOCALAPPDATA%\GolfDesk`, not in this
  repository. Golf exports themselves are unencrypted and can include course
  names, times, and GPS positions. Treat them as private.
- `research-notes.json` contains unencrypted account-scoped review notes,
  first-putt measurements, practice records and any user-imported benchmark.
  Account scoping is not encryption. These notes are not uploaded to Garmin or
  included in ordinary golf JSON exports. Back them up privately; explicitly
  exported research CSVs can also reveal personal golf information.
- Forgetting sign-in removes the local encrypted cache, not an already issued
  token at Garmin. Revoke account access through Garmin if compromise is suspected.
- Do not attach real exports, screenshots, passwords, verification codes, or
  session files to public issues. Reproduce problems with synthetic test data.
- EV and shot-strategy displays are decision aids, not validated personal
  performance predictions. Unknown outcomes and missing data must remain visible.

For a security issue, avoid posting secrets or a usable exploit against a live
account publicly. Use GitHub's private vulnerability-reporting feature if enabled,
or contact the repository owner privately before sharing sensitive details.
