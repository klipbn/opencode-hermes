# hermes-watch 3.12.0

OpenCode session observations and Telegram notifications through Hermes.
Requires Node 22.13+. This source package includes an MIT LICENSE and has no runtime npm dependencies.
The Hermes command plugin `opencode-control` is installed separately.

## Install

Copy `hermes-watch.ts` into `~/.config/opencode/plugins/hermes-watch.ts` and
start a new OpenCode process. Set up Hermes Telegram delivery and install the
`opencode-control` plugin to inspect sessions from chat.

State root: `OPENCODE_HERMES_BASE_DIR`, default `~/.cache/opencode-hermes`.
`OPENCODE_HERMES_NOTIFY` selects levels; `/ocmute` changes the runtime filter.
`OPENCODE_HERMES_AI_SUMMARY=0` disables AI summarization. Generated text is English;
original task titles, replies, and external errors are preserved.

## Development

The full repository includes tests, a TypeScript configuration, and a locked development dependency set.
From `watcher/`: `npm ci --ignore-scripts`, `npm run typecheck`, `npm test`.
Install-only ZIPs omit that test harness. [Changelog](CHANGELOG.md).
