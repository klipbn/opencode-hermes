# Changelog

All notable repository-release changes are recorded here. Repository releases follow
[Semantic Versioning](https://semver.org/) and use `vX.Y.Z` Git tags.
The watcher and control plugin keep their own independent versions and changelogs.

## [1.0.0] - 2026-10-11

### Included components

- **hermes-watch 3.10.0** — [watcher changelog](watcher/CHANGELOG.md).
- **opencode-control 1.7.0** — [control changelog](opencode-control/CHANGELOG.md).

### Added

- First bundled GitHub Release with independently versioned watcher/control source packages.
- Repository `VERSION`, release links, annotated Git tag, and SHA-256 checksums for downloadable assets.
- English setup, command references, notification examples, contributor guide, and MIT license.
- GitHub CI for Node 22.13/Python 3.9 and Node 24/Python 3.13, covering types, behavior, and packaging.

### Changed

- Replace promotional preview illustrations with dark-theme Telegram Desktop mock screenshots.
- Preserve the actual notification renderer output and explicitly identify fictional preview data.

### Compatibility

- Component runtime versions, state formats, hook definitions, and command identifiers are unchanged by this repository release.
- Repository versions identify tested source snapshots; they do not replace component versions or update installed copies automatically.

[1.0.0]: https://github.com/klipbn/opencode-hermes/releases/tag/v1.0.0
