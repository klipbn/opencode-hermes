# Installation and configuration

OpenCode Hermes consists of an OpenCode watcher and an independent Hermes command plugin.
Node 22.13+, Python 3.9+, OpenCode, and a configured Hermes Telegram gateway are required.
The watcher uses OpenCode SDK plugin types; npm dependencies are only needed for development checks.

## Watcher

From the repository root:

```sh
mkdir -p "$HOME/.config/opencode/plugins"
cp watcher/hermes-watch.ts "$HOME/.config/opencode/plugins/hermes-watch.ts"
```

Start a new OpenCode process to load this global plugin. Updating the source file does
not prove that a previously running process has loaded it. Finish active work before restarting.
Empty headless `serve`/`mcp` processes do not produce phantom terminal windows; real session
work in those processes is still observed.

## Hermes control plugin

Copy `opencode-control/` from the source tree or source ZIP to `$HERMES_HOME/plugins/`
(default `~/.hermes/plugins/`), then run:

```sh
hermes plugins enable opencode-control
hermes gateway status
```

The Python plugin has no pip dependencies. A running gateway may need a restart to load
updated commands. After its active work completes, use `hermes gateway restart`.
In Hermes, check `/ochelp`, `/hstatus`, and `/oc`. `/notifytest` sends a real message;
it is an explicit manual delivery check, not part of automated tests.

## Settings

The watcher and control plugin share `OPENCODE_HERMES_BASE_DIR` (default
`~/.cache/opencode-hermes`). Never use the Codex state root for OpenCode.

| Watcher variable | Default | Meaning |
|---|---|---|
| `OPENCODE_HERMES_HEARTBEAT_MS` | `10000` | Process heartbeat interval |
| `OPENCODE_HERMES_STATE_RETENTION_HOURS` | `168` | State retention |
| `OPENCODE_HERMES_CMD_TIMEOUT_MS` | `30000` | External command timeout |
| `OPENCODE_HERMES_SUMMARY_TIMEOUT_MS` | `120000` | AI summary timeout |
| `OPENCODE_HERMES_WAITING_REMINDER_MIN` | `10` | Permission reminders; at most three |
| `OPENCODE_HERMES_LONG_RUN_MIN` | `0` | Long-running turn reminder; `0` disables |
| `OPENCODE_HERMES_AI_SUMMARY` | `1` | AI summary; `0` uses a factual fallback |
| `OPENCODE_HERMES_SUMMARY_PROVIDER` | Hermes default | Summary provider |
| `OPENCODE_HERMES_SUMMARY_MODEL` | Hermes default | Summary model |
| `OPENCODE_HERMES_NOTIFY` | `done,permission,reminder,retry,error` | Enabled notification levels |
| `OPENCODE_HERMES_TG_RICH` | `1` | Try rich delivery; `0` always uses fallback HTML |
| `OPENCODE_HERMES_TG_TIMEOUT_MS` | `15000` | Bot API request timeout |
| `OPENCODE_HERMES_TG_TOKEN` | Hermes Telegram token | Explicit Bot API credential override |
| `OPENCODE_HERMES_TG_CHAT_ID` | Hermes home chat | Notification recipient override |

The token falls back to `TELEGRAM_BOT_TOKEN` and the Hermes `.env`. The chat is resolved
through `hermes send --list telegram --json`. Credentials remain outside the repository.

| Control variable | Default |
|---|---|
| `OC_CONTROL_MAX_AGE_HOURS` | `24` |
| `OC_CONTROL_HEARTBEAT_FRESH_SECONDS` | `35` |
| `OC_CONTROL_STALE_AFTER_MINUTES` | `45` |
| `OC_CONTROL_MAX_LIST_ROWS` | `15` |

Invalid numeric values fall back to defaults. `/ocmute` changes runtime delivery settings;
the watcher reads `control.json` with an approximately two-second cache.

## Notification behavior

All generated text is English. AI summaries request three short factual bullets and treat
agent output as untrusted data. With AI disabled/unavailable, the factual fallback includes
the original answer excerpt. Titles, answers, test commands, paths, and external errors are
preserved and HTML-escaped at presentation. Stored content is not HTML-escaped.

Done/error notifications try `sendRichMessage`; unsupported methods, missing credentials,
timeouts, and request errors fall back to `hermes send`. Short events use Hermes directly.
The first line starts with `OpenCode ·` and the session title; footer dates use English
and Moscow time. Aborted turns remain in the journal without a Telegram notification.

## Updating

Installed files are copies; a Git pull does not update them. Back up existing plugin files,
replace them with inspected sources, and retain all state and mute settings. Restart the
Hermes gateway and use a new OpenCode process when it is safe to finish active work.
