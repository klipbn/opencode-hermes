# Contributing

Keep changes focused and preserve the watcher/control data contract.
All maintained documentation, comments, metadata, and generated UI text are English.
User data is not translated. Unicode fixtures may use escapes to distinguish input data
from product text. Source filenames and command names stay stable across releases.

## Checks

From the project root, follow the development commands in [README.md](README.md).
Run Python syntax checks as well:

```sh
python3 -m py_compile opencode-control/__init__.py scripts/package.py
```

Write a behavior test before changing notification rendering, lifecycle coordination,
state parsing, or delivery rules. Use temporary directories and substitute only the
external SDK, process, and network boundaries. Never send real Telegram messages in tests.

Existing input aliases, optional state fields, unknown metrics, and explicit warnings
are compatibility behavior. Do not replace unknown values with successful outcomes or zero.

## Versions

Watcher and control have separate SemVer versions and changelogs. See
[docs/releasing.md](docs/releasing.md). Commits and PR descriptions should be English
and describe observable behavior and the checks actually run.

## Local material

`archive/` and `docs/history/` preserve pre-publication originals locally and are ignored.
They are historical records, not instructions for current development. Do not add credentials,
gateway configuration, real state, session content, or generated dependencies to Git.
