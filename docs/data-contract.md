# OpenCode state contract

The shared root is `OPENCODE_HERMES_BASE_DIR`, default `~/.cache/opencode-hermes`.

| Object | Path | Owner |
|---|---|---|
| Session state | `sessions/<sanitized-sessionID>.json` | Watcher |
| Process heartbeat | `instances/<pid>-<uuid>.json` | Watcher |
| Mute settings | `control.json` | Control plugin |
| Summary prompts | `tmp/` | Watcher |

The watcher owns state writes. Control reads it, writes mute settings, and can remove old
session files through explicitly requested `/occlean`. All state updates use a same-directory
temporary file and atomic rename, with read-modify-write serialization by session ID.

Session state includes status, test observations, SDK session diff, and up to 30 turn records.
Optional usage fields represent actual SDK observations; unavailable values are not invented.
Diff stores up to 200 files sorted by change size while totals reflect the full SDK result.
The last test list is limited to 10. Default state retention is 168 hours; temporary prompts
expire after two hours. Data directories are 0700 and files 0600.

## Turns and processes

Optional `turnID`, `turnFinalization` (`preparing` / `sending` / `finished`), and per-record
turn identifiers coordinate one finalization within a process. An error can cancel a preparing
completion, but not a delivery already claimed. SDK, summary, and delivery work runs outside
the state write lock. Late results update the old journal record without changing a new turn.
This is not an inter-process lock or a crash-safe exactly-once delivery protocol.

Subagent tools resolve to their root session. Heartbeats for a shared PID are collapsed by
control, retaining statuses from all instances. Empty headless processes do not create windows.
Status comes from official events; bootstrap and heartbeat do not call session SDK methods.

## Compatibility

The English interface changes labels, not field names or command identifiers. Previous
state and mute files remain readable; old stored summaries stay as recorded. Features needing
a turn journal explicitly warn on pre-3.6 state instead of presenting misleading totals.
Unknown/missing exit codes stay `unknown`. Overall repository git diff is never substituted
for the SDK session diff. Aborted turns are recorded without notification.

Review both writer and reader whenever the contract changes. Preserve backward compatibility
for at least one previous major version, and document any honest feature degradation.
