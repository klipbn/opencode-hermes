# hermes-watch changelog

Versions follow [Semantic Versioning](https://semver.org/). The watcher and control plugin are versioned independently.

## 3.11.0

- Replace the visible `OpenCode ·` notification prefix with `▣ OC ·`, using a square-ring glyph modeled on the opencode logo mark and the `OC` abbreviation. Notification structure, escaping, and fallback behavior are unchanged.

## 3.10.0

- Publish the watcher with English notifications, logs, comments, metadata, and AI summary instructions.
- Format notification dates in `en-GB`, using 24-hour Moscow time (`Europe/Moscow`, MSK). Use `h`, `min`, and `s` for durations and English file counts.
- Preserve session titles, assistant responses, and external errors in their original language. Keep existing state fields, environment settings, and hook behavior compatible.
- Escape dynamic summaries in fallback Telegram HTML, matching the existing rich-notification protection. Stored summaries remain unchanged.
- Add regression coverage for English rich/fallback messages, Unicode payload preservation, duration/date formatting, and nonce-protected factual summary prompts.

## 3.9.0

- Normalize the previous `3.9-turns` label to SemVer when splitting the projects.
- Use the stable source filename `hermes-watch.ts`; preserve state contracts and event processing.
- Share the lifecycle queue and atomic turnID claim across watcher factories. Concurrent idle/error events do not duplicate turn history.
- Allow error to cancel done preparation before the delivery claim. Events after delivery starts do not initiate another notification.
- Snapshot tests and tool counts at finalization. Delayed results cannot change the next turn's status, tests, or diff. Late test output checks turnID; conversation tails stop at the finalization time.
- Record MessageAbortedError as an interrupted turn without Telegram delivery.
- Prefix every notification with `OpenCode ·` and log delivery outcomes.
- Add optional turnID/turnFinalization fields compatible with older control versions.
- Preserve the local guard against unexpected process.argv values.

## 3.8.0

- Suppress empty instance heartbeats for headless `opencode serve` and `opencode mcp` processes, avoiding phantom windows in `/oc`. Heartbeats and notifications resume when real session activity appears.
- Add an optional `headless` flag to instance heartbeats.

## 3.7.0

- Put the session title on the first notification line for Telegram chat previews, followed by status, project, duration, and cost. Fall back to the project name when no title exists.
- Send done/error notifications through Telegram Bot API `sendRichMessage` (Bot API 10.1+), with expanded Summary, collapsed Diff/Tests/Details sections, and a readable Moscow-time footer. Collapsed notifications take two or three lines instead of roughly thirty plain-text lines.
- Fall back to `hermes send` on missing credentials, timeout, or an unavailable rich method. Use expandable blockquotes for Diff and Tests.
- Read the bot token from OPENCODE_HERMES_TG_TOKEN or TELEGRAM_BOT_TOKEN in ~/.hermes/.env. Read the chat ID from OPENCODE_HERMES_TG_CHAT_ID or the Hermes home chat (`hermes send --list telegram --json`). Cache credentials without logging them.
- Support OPENCODE_HERMES_TG_RICH=0 to disable rich delivery and OPENCODE_HERMES_TG_TIMEOUT_MS for the HTTP timeout (15 seconds by default).
- Escape dynamic HTML data including commands, titles, and summaries so `<`, `>`, and `&` cannot break notification markup.
- Keep the state and heartbeat format compatible with opencode-control v1.4+.

## 3.6.0

- Store up to 30 turn records with duration, diff totals, test results, tool counts, tokens, and cost. Previously only the latest turn was retained, making daily `/today` totals inaccurate.
- Sum token usage and cost across assistant messages after the last user message. Omit unavailable SDK metrics rather than fabricate them.
- Track per-turn tool counts in memory without additional disk writes.
- Add done/permission/reminder/retry/error notification categories, the persistent OPENCODE_HERMES_NOTIFY filter, and temporary mute through control.json written by `/ocmute`.
- Remind about unanswered permission requests through OPENCODE_HERMES_WAITING_REMINDER_MIN (10 minutes by default, at most three reminders).
- Add optional long-turn notifications through OPENCODE_HERMES_LONG_RUN_MIN, disabled by default.
- Deduplicate identical errors within five minutes.
- Store each test's durationMs.
- Sort diffs by change volume before truncating to 200 files, keeping the largest changes.
- Include notifyLevels and muteUntil in heartbeats so `/hstatus` reports actual settings.
- Support OPENCODE_HERMES_BASE_DIR to override the state root.

## 3.5.0

- Write state and heartbeat files atomically using a temporary file and rename.
- Serialize read-modify-write operations per sessionID.
- Apply patches over existing state rather than overwrite entire objects.
- Resolve tool hooks to the root session, avoiding phantom subagent sessions.
- Set unfinished running tests to unknown at turn completion.
- Use node:child_process with timeouts and wrap hooks in safeRun.
- Enforce 0700 directories and 0600 files, startup cleanup, and bounded diff storage.
- Protect summary prompts with nonce delimiters, strip ANSI sequences, and sanitize session IDs.
