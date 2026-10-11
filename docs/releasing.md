# Releases

The watcher and Hermes control plugin are versioned independently using SemVer:
MAJOR for incompatible changes, MINOR for compatible capabilities, PATCH for fixes.
The English interface is recorded as a compatible minor update.

## Repository releases

`VERSION` is the repository release version; `CHANGELOG.md` records changes and the included
watcher/control versions. Repository tags use `vX.Y.Z`. Component metadata remains independent:
a documentation-only repository release does not bump either runtime component unnecessarily.

1. Update `VERSION`, the root changelog, and the README release link together.
2. If runtime behavior changes, also bump the affected component metadata and changelog as described below.
3. Run all checks, regenerate and visually inspect preview assets, and inspect the final diff.
4. Build both component ZIPs and create `dist/SHA256SUMS` from those two release assets only.
5. Commit the release snapshot and verify GitHub CI for that exact commit.
6. Create an annotated `vX.Y.Z` tag for the verified commit and push the tag.
7. Create the GitHub Release with `--verify-tag`, English notes from the root changelog,
   the two inspected component ZIPs, and `SHA256SUMS`.
8. Verify the published tag resolves to the expected commit and downloaded assets match the checksums.

Each repository release is a tested pair of components. A later component-only release may
use its own tag and changelog without forcing the other component's version to change.

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

Optional component-only release tags are `watcher-vX.Y.Z` and `control-vX.Y.Z`. Review each published
artifact against the corresponding tagged sources. Creating tags or uploading releases
is a separate explicit action; the local packaging script does neither.

Updating a repository does not update installed copies. Apply an inspected release to
the appropriate installation directory. Keep state and `control.json` intact. For an
OpenCode watcher update, start a new OpenCode process after ongoing work completes.
