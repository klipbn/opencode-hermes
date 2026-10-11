# Releases

The watcher and Hermes control plugin are versioned independently using SemVer:
MAJOR for incompatible changes, MINOR for compatible capabilities, PATCH for fixes.
The English interface is recorded as a compatible minor update.

## Prepare a watcher release

1. Update `watcher/package.json` and `WATCHER_VERSION` in `hermes-watch.ts` together.
2. Update the lockfile with `npm install --prefix watcher --package-lock-only --ignore-scripts`.
3. Update `watcher/CHANGELOG.md`, the README version table, and the component README.
4. Run all checks from [CONTRIBUTING.md](../CONTRIBUTING.md).
5. Run `python3 scripts/package.py watcher` and inspect `dist/hermes-watch-vX.Y.Z.zip`.

## Prepare a control release

1. Update `opencode-control/plugin.yaml` and `PLUGIN_VERSION` in `__init__.py` together.
2. Update `opencode-control/CHANGELOG.md`, the README version table, and the component README.
3. Run all checks and `python3 scripts/package.py control`.
4. Inspect `dist/opencode-control-vX.Y.Z.zip`.

Each ZIP has a component-named top-level folder containing its source, metadata, README,
changelog, and MIT LICENSE. File inclusion is explicit and ZIP metadata is fixed; the same
inputs produce the same archive. The build refuses inconsistent version declarations.

Future release tags are `watcher-vX.Y.Z` and `control-vX.Y.Z`. Review each published
artifact against the corresponding tagged sources. Creating tags or uploading releases
is a separate explicit action; the local packaging script does neither.

Updating a repository does not update installed copies. Apply an inspected release to
the appropriate installation directory. Keep state and `control.json` intact. For an
OpenCode watcher update, start a new OpenCode process after ongoing work completes.
