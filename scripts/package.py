"""Build one source release without installation, networking, or message delivery."""
import argparse
import json
from pathlib import Path
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
WATCHERS = {
    "hermes-watch": ("hermes-watch.ts",),
    "codex-watch": ("codex-watch.ts", "codex-daemon.ts"),
}


def constant(path, name):
    match = re.search(r"\b" + name + r"\s*=\s*['\"]([^'\"]+)['\"]", path.read_text())
    if not match:
        raise ValueError(f"Missing {name} in {path.name}")
    return match.group(1)


def package(component):
    if component == "watcher":
        folder = ROOT / "watcher"
        metadata = json.loads((folder / "package.json").read_text())
        name, version = metadata["name"], metadata["version"]
        filenames = (*WATCHERS[name], "package.json", "README.md", "CHANGELOG.md")
        reported = constant(folder / filenames[0], "WATCHER_VERSION")
    else:
        manifests = list(ROOT.glob("*-control/plugin.yaml"))
        if len(manifests) != 1:
            raise ValueError("Expected exactly one control plugin source directory")
        manifest = manifests[0]
        folder = manifest.parent
        text = manifest.read_text()
        name = re.search(r"^name:\s*([^\s]+)", text, re.M).group(1)
        version = re.search(r"^version:\s*['\"]?([^\s'\"]+)", text, re.M).group(1)
        if name != folder.name:
            raise ValueError("The plugin.yaml name must match the plugin directory")
        filenames = ("__init__.py", "plugin.yaml", "README.md", "CHANGELOG.md")
        reported = constant(folder / "__init__.py", "PLUGIN_VERSION")
    if version != reported:
        raise ValueError(f"Versions do not match for {name}: metadata={version}, source={reported}")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
        raise ValueError(f"Expected a SemVer version, received: {version}")
    # Explicit inclusion keeps credentials, caches, and unrelated files out of releases.
    contents = {filename: (folder / filename).read_bytes() for filename in filenames}
    contents["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    output = ROOT / "dist" / f"{name}-v{version}.zip"
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for filename, data in sorted(contents.items()):
                info = ZipInfo(f"{name}/{filename}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("watcher", "control"))
    args = parser.parse_args()
    try:
        print(package(args.component).relative_to(ROOT))
    except (ValueError, KeyError, OSError, AttributeError) as error:
        print(f"Build rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
