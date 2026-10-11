"""Reject untranslated Cyrillic in Git-tracked text; retain local archives and binary assets."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile(r"[\u0400-\u052f]")


def main():
    try:
        names = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
    except subprocess.CalledProcessError:
        print("Run this check in an initialized Git repository.", file=sys.stderr)
        return 2
    problems = []
    for name in filter(None, names):
        try:
            text = (ROOT / name).read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if CYRILLIC.search(line):
                problems.append(f"{name}:{number}")
    if problems:
        print("Untranslated Cyrillic in tracked text:\n" + "\n".join(problems), file=sys.stderr)
        return 1
    print("Maintained tracked text is free of untranslated Cyrillic.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
