# opencode-control changelog

## 1.8.0

- Replace the visible `OpenCode ·` header prefix in `/oc`, `/ocstats`, `/today`, `/ocproj`, problems, and models output with `▣ OC ·`, a square-ring glyph modeled on the opencode logo mark plus the `OC` abbreviation. Commands, parsing, and state handling are unchanged.

## 1.7.0

- English command descriptions, help, status messages, and diagnostics.
- English singular/plural forms for durations and activity counts.
- Preserve user-provided text and the legacy history alias.
- Source and packaging moved into an independent project.

## 1.6.2

- **fix:** one OpenCode process is shown as one window in `/oc` again.
  OpenCode instantiates the global watcher plugin once per project
  directory inside a single process (e.g. `opencode run` started from
  home, plus the session's project directory), so one process could
  emit several instance heartbeats and appear as a phantom extra
  window ("OpenCode window is open; no task has started yet").
  Live instances are now collapsed per PID: the heartbeat owning the
  current session wins, and `statuses` are merged so session
  resolution (`/oc`, `/oc all`, `/ocstats`, `/ocproj`, `/today`)
  keeps working. No state-format changes.

## 1.6.1

- **docs:** recommended watcher bumped to v3.7 (rich Telegram
  notifications via Bot API `sendRichMessage`, title-first headers).
  No code or state-contract changes — v1.6.0 stays fully compatible.

## 1.6

New commands: `/ochelp`, `/ocsum`, `/ocdiff`, `/octests`, `/ocfind`,
`/ocproj`, `/ocstats`, `/ocmute`, `/occlean`.

- `/ocstats` and `/ocproj` aggregate the watcher's turn log, so they
  report real per-turn time, diffs, tests and cost rather than the last
  saved snapshot of each session.
- `/today` switches to the turn log when it exists. Previously it summed
  only the last turn of each session — several turns in a row were
  invisible. The old block is still shown for pre-v3.6 watchers, now
  labelled honestly, so the same report never carries two different
  denominators.
- `/ocmute` gives the watcher a runtime kill switch for notifications
  (all, or by type: done / permission / reminder / retry / error).
- `/ocdiff` lists every file, largest change first, instead of the 12
  the session view can fit.
- `/occlean` reclaims state files, with a hard floor at 24h.
- `/hstatus` shows notification state and warns when a mute is set but
  no live watcher has acknowledged it.
- Shared target resolution: every per-session command takes a window
  number, a session id, or nothing.

## 1.5

- **fix:** naive timestamps no longer crash every command with a
  tz-aware/naive `TypeError`
- **fix:** `/oclast` again finds the last finished session after its
  window was closed
- **fix:** `/today` pointed at `/ocstats`, which was never registered
  (it exists now)
- **fix:** `/today` counted finished work only as IDLE, so closed
  windows silently disappeared from the daily total
- **perf:** one process-table snapshot per command instead of a `ps`
  subprocess per PID
- **ux:** `/oc all` addresses rows by `session_id`, because its row
  numbers never matched the live-window numbers used by `/oc <N>`
- hardening: bad env values, oversized/corrupt state files, zero-size
  disk, malformed `/proc/meminfo`, zombie PIDs, non-dict state values

## 1.4

- `/oc` means CURRENT LIVE OPENCODE WINDOWS, not session history
- one `/oc` row = one alive OpenCode PID/heartbeat
- `/oc all` keeps the 24h session history
- old IDLE becomes CLOSED when its owning OpenCode process is gone

## 1.3 / v1.3.1

- PID/process-aware CLOSED detection, `/occlosed`
- STALE = process alive but watcher heartbeat stale

## 1.2

- `/models [days]` from `opencode stats`

## 1.1

- macOS + Linux system diagnostics
