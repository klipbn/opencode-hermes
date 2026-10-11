# opencode-hermes: development instructions

Sources: `watcher/` and `opencode-control/`. See the installation, state contract, and release
guides in `docs/`. Historical files under `archive/` or `docs/history/` do not replace these instructions.

## Authorization

Local edits and tests are allowed. Commits, pushes, repository creation, messages, deployment,
and restarts require explicit current-chat authorization. Tool availability is not permission.
Only delegate when the user or an applicable skill explicitly requests delegation.
Do not commit credentials, real state, session content, caches, or private configuration.

## Compatibility and invariants

- Wrap hooks in safeRun so plugin failures do not interrupt OpenCode.
- Serialize updates by session ID, atomically replace files, and patch over previous values.
- Lifecycle queues, turn claims, and tool counters are shared by module factories within a process.
- Resolve subagent tools to the root session. Preserve per-PID heartbeat collapse.
- SDK supplies session diffs; never substitute repository git status.
- No SDK calls during bootstrap/heartbeat and no custom SIGINT handler.
- AI summaries use a nonce-delimited data block, one Hermes turn, and no tools.
- English fallback summaries must escape HTML at rendering, not mutate stored text.
- Use same-directory atomic writes, restrictive data permissions, and defensive numeric environment parsing.
- Control reads watcher state and owns mute settings. Preserve existing command names and input aliases.
- Missing exit codes are unknown. Unavailable metrics stay unavailable, not zero or repository-wide substitutes.
- HTML escape all dynamic display content; do not escape or translate stored raw data.
- Preserve English generated text, original Unicode user content, and documented rich/fallback behavior.
- Do not claim a successful delivery proves the recipient read it.
- Preserve backward compatibility with at least one previous major version; warn on missing capabilities.

## Style, versions, checks

All maintained comments, documentation, metadata, test names, and generated UI are English.
Keep filenames stable; watcher and control have independent SemVer versions and changelogs.
Watcher version appears in package.json, package-lock.json, and WATCHER_VERSION.
Control version appears in plugin.yaml and PLUGIN_VERSION. Test actual reader/writer behavior.

Watcher runtime uses Node built-ins (and OpenCode plugin types for OpenCode); Python uses stdlib.
Run typecheck, Node/Python tests, syntax checks, and source packaging from README/CONTRIBUTING.
Never use live Telegram delivery or production state in tests. Review the actual staged diff
before publishing, and distinguish local checks, GitHub CI, and deployed-version verification.
