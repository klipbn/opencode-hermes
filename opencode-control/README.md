# OpenCode Control 1.9.0

A Hermes command plugin for sessions recorded by hermes-watch. Reads local state,
does not call an LLM, and exposes live windows, turn results, statistics, and mute controls.
Recommended watcher: hermes-watch 3.12.0. Earlier 3.4+ state remains readable; features
requiring the 3.6+ turn journal explicitly warn when it is unavailable.

## Install

Copy this `opencode-control` folder into `$HERMES_HOME/plugins/` (default `~/.hermes/plugins/`),
then run `hermes plugins enable opencode-control`. Restart an already running gateway
after active work finishes if the commands have not been loaded. The plugin uses Python stdlib only.

## Commands

| Command | Purpose |
|---|---|
| `/oc` | Currently observed OpenCode windows, one per live PID |
| `/oc <number>` | One current window |
| `/oc <session_id>` | A session from current or historical state |
| `/oc all` | Sessions from the history window |
| `/ocsum [target]` | Last completed turn: summary, diff, tests, cost |
| `/ocdiff [target]` | Recorded file changes, largest first |
| `/octests [target]` | Test commands, exit codes, and durations |
| `/oclast` | Last completed session, including closed windows |
| `/occlosed` | Sessions whose associated process is gone |
| `/ocwait` | WAITING, ERROR, RETRY, STALE, or UNKNOWN observations |
| `/ocstats [days]` | Turn-journal activity, tests, usage, projects, and models |
| `/ocproj [name]` | Seven-day project activity |
| `/ocfind <text>` | Search titles, projects, summaries, and changed paths |
| `/today` | Today's recorded activity |
| `/errors` | Recent problem observations |
| `/models [days]` | Usage returned by the OpenCode stats CLI |
| `/ocmute [minutes\|off\|levels]` | Pause or filter notifications |
| `/occlean [days]` | Delete old session state, never anything younger than 24 hours |
| `/hstatus` | Gateway, watcher, and notification configuration |
| `/sys` | Local CPU, RAM, disk, load, and process observations |
| `/ochelp` | Help generated from the command registry |
| `/notifytest` | Explicitly send a real proactive Telegram test message |

`target` is a current `/oc` number, a session ID/prefix, or empty for the current window
or most recently completed session. History numbers do not identify current windows.
Titles, summaries, paths, and external errors are displayed as recorded, not translated.

## State and settings

`OPENCODE_HERMES_BASE_DIR` defaults to `~/.cache/opencode-hermes`. The watcher owns
session/instance state. `/ocmute` writes `control.json`; the watcher reads it within about
two seconds. `/occlean` explicitly removes old session files.

| Variable | Default |
|---|---|
| `OC_CONTROL_MAX_AGE_HOURS` | `24` |
| `OC_CONTROL_HEARTBEAT_FRESH_SECONDS` | `35` |
| `OC_CONTROL_STALE_AFTER_MINUTES` | `45` |
| `OC_CONTROL_MAX_LIST_ROWS` | `15` |

Invalid numeric settings fall back to defaults. Missing usage/diff/test observations are
reported as unavailable; no repository-wide git diff is substituted. A failed/missing test
exit code is never displayed as a pass. Statistics reflect retained data, not all-time accounting.

Full setup: https://github.com/klipbn/opencode-hermes/blob/main/docs/installation.md

## History and license

[CHANGELOG.md](CHANGELOG.md). MIT; the source release includes its LICENSE.
