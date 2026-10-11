"""
 Hermes plugin: OpenCode Control Center v1.8.0 (live windows, macOS/Linux).

Slash commands:
  /oc [N|session_id|all]  - live OpenCode windows or session details
  /ochelp                 - all commands with hints
  /occlosed               - recently closed OpenCode sessions
  /oclast                 - last completed OpenCode session
  /ocwait                 - sessions that need attention
  /ocsum [target]         - short summary of a session's last turn
  /ocdiff [target]        - full changed-file list of a session
  /octests [target]       - test runs of a session with exit codes
  /ocfind <query>         - search sessions by title/project/summary/file
  /ocproj [name]          - per-project rollup over the turn log
  /ocstats [days]         - aggregated activity from the watcher turn log
  /ocmute [min|off]       - pause watcher Telegram notifications
  /occlean [days]         - drop old watcher state files
  /today                  - today's OpenCode activity summary
  /errors                 - recent OpenCode problem sessions
  /sys                    - workstation health
  /hstatus                - Hermes + watcher health
  /models [days]          - OpenCode model usage/cost for last N days
  /notifytest             - test proactive Hermes -> Telegram delivery

`target` is a live-window number, a session_id prefix, or empty for the
most relevant session.

Reads hermes-watch state from:
  ~/.cache/opencode-hermes/sessions/
  ~/.cache/opencode-hermes/instances/

No LLM calls are made by this plugin.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import platform
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PLUGIN_VERSION = "1.8.0"

HOME = Path.home()
HERMES_HOME = Path(os.environ.get("HERMES_HOME", HOME / ".hermes"))

BASE_DIR = Path(
    os.environ.get(
        "OPENCODE_HERMES_BASE_DIR",
        HOME / ".cache" / "opencode-hermes",
    )
)
STATE_DIR = BASE_DIR / "sessions"
INSTANCE_DIR = BASE_DIR / "instances"
CONTROL_PATH = BASE_DIR / "control.json"

# Notification levels supported by hermes-watch v3.6+.
NOTIFY_LEVELS = ["done", "permission", "reminder", "retry", "error"]

OPENCODE_PLUGIN_DIR = HOME / ".config" / "opencode" / "plugins"


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """Invalid environment values must not crash the plugin."""
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except Exception:
        return default

    return max(minimum, value)


MAX_AGE_HOURS = env_int("OC_CONTROL_MAX_AGE_HOURS", 24)
HEARTBEAT_FRESH_SECONDS = env_int(
    "OC_CONTROL_HEARTBEAT_FRESH_SECONDS", 35
)
STALE_AFTER_MINUTES = env_int("OC_CONTROL_STALE_AFTER_MINUTES", 45)
MAX_LIST_ROWS = env_int("OC_CONTROL_MAX_LIST_ROWS", 15)

# Reject unusually large state files.
MAX_STATE_FILE_BYTES = 8 * 1024 * 1024

# Cache the process table: one ps per command, rather than per PID.
PROC_SNAPSHOT_TTL_SECONDS = 3.0


ICONS = {
    "busy": "🟡",
    "waiting": "🔐",
    "retry": "🟠",
    "error": "🔴",
    "unknown": "❔",
    "stale": "💤",
    "closed": "⚫️",
    "ready": "🟢",
    "idle": "⚪️",
}

LABELS = {
    "busy": "BUSY",
    "waiting": "WAITING",
    "retry": "RETRY",
    "error": "ERROR",
    "unknown": "UNKNOWN",
    "stale": "STALE",
    "closed": "CLOSED",
    "ready": "OPEN",
    "idle": "IDLE",
}

PRIORITY = {
    "waiting": 0,
    "error": 1,
    "retry": 2,
    "busy": 3,
    "unknown": 4,
    "stale": 5,
    "ready": 6,
    "idle": 7,
    "closed": 8,
}

LIVE_WINDOW_STATUSES = {
    "busy",
    "waiting",
    "retry",
    "error",
    "idle",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def parse_dt(value: Any) -> datetime | None:
    """
    Return a timezone-aware datetime. Legacy naive timestamps are treated as UTC
    to avoid mixing naive and aware datetimes in command arithmetic.
    """
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except Exception:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed


def human_duration(seconds: float | int | None) -> str:
    try:
        seconds = max(0, int(seconds or 0))
    except Exception:
        return "?"

    if seconds < 60:
        return f"{seconds}s"

    minutes = seconds // 60

    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    minutes %= 60

    if hours < 24:
        return f"{hours}h {minutes}m"

    days = hours // 24
    hours %= 24
    return f"{days}d {hours}h"


# Keep the legacy helper name and signature for existing integrations.
def plural_ru(
    count: int,
    one: str,
    few: str,
    many: str,
) -> str:
    count = abs(int(count))

    return one if count == 1 else many


def short_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()

    if len(text) <= limit:
        return text

    return text[: max(0, limit - 1)] + "…"


ANSI_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def compact_path(value: Any) -> str:
    if not value:
        return "?"

    path = str(value)
    home = str(HOME)

    if path == home:
        return "~"

    if path.startswith(home + os.sep):
        return "~" + path[len(home):]

    return path


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def as_dict(value: Any) -> dict[str, Any]:
    """State comes from disk and may contain arbitrary values."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def run_command(
    args: list[str],
    timeout: float = 8.0,
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return 127, "", f"command not found: {args[0] if args else '?'}"
    except Exception as exc:
        return 125, "", str(exc)


def load_json_files(directory: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    if not directory.exists():
        return result

    for file in sorted(directory.glob("*.json")):
        try:
            if file.stat().st_size > MAX_STATE_FILE_BYTES:
                continue

            data = json.loads(
                file.read_text(encoding="utf-8")
            )

            if isinstance(data, dict):
                data["_file"] = str(file)
                result.append(data)
        except Exception:
            # Skip corrupt or partially written files.
            continue

    return result


# ---------------------------------------------------------------------------
# Process table
# ---------------------------------------------------------------------------

_PROC_CACHE: dict[str, Any] = {"at": -1e9, "table": {}}


def system_name() -> str:
    return platform.system().lower()


def _read_process_table() -> dict[int, str]:
    """pid -> lowercased command line."""
    table: dict[int, str] = {}

    if system_name() == "linux":
        proc = Path("/proc")

        if proc.exists():
            for item in proc.iterdir():
                if not item.name.isdigit():
                    continue

                try:
                    raw = (
                        item.joinpath("cmdline")
                        .read_bytes()
                        .replace(b"\x00", b" ")
                        .decode("utf-8", errors="ignore")
                        .strip()
                        .lower()
                    )
                except Exception:
                    continue

                if raw:
                    table[int(item.name)] = raw

            if table:
                return table

    for flags in (
        ["ps", "-A", "-o", "pid=,args="],
        ["ps", "-A", "-o", "pid=,command="],
    ):
        code, stdout, _ = run_command(flags, timeout=6)

        if code != 0 or not stdout:
            continue

        for line in stdout.splitlines():
            line = line.strip()

            if not line:
                continue

            pid_text, _, command = line.partition(" ")

            if not pid_text.isdigit():
                continue

            table[int(pid_text)] = command.strip().lower()

        if table:
            break

    return table


def process_table(force: bool = False) -> dict[int, str]:
    now = time.monotonic()

    if (
        not force
        and now - float(_PROC_CACHE["at"]) < PROC_SNAPSHOT_TTL_SECONDS
    ):
        return _PROC_CACHE["table"]

    _PROC_CACHE["table"] = _read_process_table()
    _PROC_CACHE["at"] = now

    return _PROC_CACHE["table"]


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def pid_command(pid: Any) -> str | None:
    if not isinstance(pid, int) or pid <= 0:
        return None

    table = process_table()

    if pid in table:
        return table[pid]

    # A process may have started after the snapshot: refresh once, then query its PID.
    table = process_table(force=True)

    if pid in table:
        return table[pid]

    code, stdout, _ = run_command(
        ["ps", "-p", str(pid), "-o", "command="],
        timeout=4,
    )

    if code != 0 or not stdout.strip():
        return None

    return stdout.strip().lower()


def pid_is_opencode(pid: Any) -> bool:
    command = pid_command(pid)

    if not command:
        return False

    lower = command.lower()

    if "defunct" in lower:
        return False

    return bool(
        re.search(r"(^|[/\s])opencode(?:\s|$)", lower)
        or "opencode.ai" in lower
    )


def owning_process_state(
    state: dict[str, Any],
) -> str:
    """
    Returns:
      opencode  - PID exists and still looks like OpenCode
      dead      - PID no longer exists
      reused    - PID exists but belongs to something else
      unknown   - old state has no usable PID
    """
    pid = state.get("pid")

    if not isinstance(pid, int) or pid <= 0:
        return "unknown"

    if not pid_alive(pid):
        return "dead"

    if pid_is_opencode(pid):
        return "opencode"

    return "reused"


# ---------------------------------------------------------------------------
# OpenCode live-state resolution
# ---------------------------------------------------------------------------

def load_live_instances(
    now: datetime,
) -> dict[str, dict[str, Any]]:
    instances: dict[str, dict[str, Any]] = {}

    for item in load_json_files(INSTANCE_DIR):
        heartbeat = parse_dt(item.get("heartbeatAt"))
        pid = item.get("pid")
        instance_id = item.get("instanceID")

        if not heartbeat or not instance_id:
            continue

        heartbeat_age = (now - heartbeat).total_seconds()

        alive = (
            heartbeat_age <= HEARTBEAT_FRESH_SECONDS
            and pid_alive(pid)
        )

        item["_heartbeat"] = heartbeat
        item["_heartbeat_age"] = heartbeat_age
        item["_alive"] = alive

        if alive:
            instances[str(instance_id)] = item

    return collapse_instances_by_pid(instances)


def _instance_rank(item: dict[str, Any]) -> tuple[int, int, float]:
    """
    Rank instances sharing a PID: prefer a current session, then more live
    statuses, then the newest heartbeat.
    """
    heartbeat = item.get("_heartbeat")

    return (
        1 if item.get("currentSessionID") else 0,
        len(as_dict(item.get("statuses"))),
        heartbeat.timestamp() if isinstance(heartbeat, datetime) else 0.0,
    )


def collapse_instances_by_pid(
    instances: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    One OpenCode process is one window. The global watcher is instantiated
    per project directory within a process, producing several heartbeats.
    Keep the most informative instance and merge statuses so match_instance
    can still resolve sessions referencing the discarded instances.
    """
    best: dict[str, dict[str, Any]] = {}
    merged: dict[str, dict[str, Any]] = {}

    for item in instances.values():
        key = (
            str(item.get("pid"))
            if item.get("pid") is not None
            else str(item.get("instanceID"))
        )

        previous = best.get(key)

        if (
            previous is None
            or _instance_rank(item) > _instance_rank(previous)
        ):
            best[key] = item

        bucket = merged.setdefault(key, {})
        bucket.update(as_dict(item.get("statuses")))

    for key, item in best.items():
        item["statuses"] = (
            merged.get(key) or as_dict(item.get("statuses"))
        )

    return {
        str(item.get("instanceID")): item
        for item in best.values()
    }


def match_instance(
    state: dict[str, Any],
    live_instances: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    instance_id = state.get("instanceID")

    if instance_id and str(instance_id) in live_instances:
        return live_instances[str(instance_id)]

    # Backward compatibility with old watcher states.
    session_id = state.get("sessionID")
    directory = state.get("directory")

    for instance in live_instances.values():
        if directory and instance.get("directory") != directory:
            continue

        statuses = as_dict(instance.get("statuses"))

        if session_id in statuses:
            return instance

    return None


def effective_status(
    state: dict[str, Any],
    instance: dict[str, Any] | None,
    now: datetime,
) -> tuple[str, float]:
    stored = str(state.get("status", "unknown"))

    updated = parse_dt(state.get("updatedAt"))
    started = parse_dt(
        state.get("turnStartedAt") or state.get("startedAt")
    )

    age_seconds = (
        (now - updated).total_seconds()
        if updated
        else 10**12
    )

    run_seconds = (
        (now - started).total_seconds()
        if started
        else age_seconds
    )

    process_state = owning_process_state(state)

    # A state explicitly belongs to a currently alive watcher instance.
    if instance:
        live_status = None

        if instance.get("statusOk"):
            live_status = as_dict(instance.get("statuses")).get(
                state.get("sessionID")
            )

        if stored == "waiting":
            return "waiting", run_seconds

        if isinstance(live_status, dict):
            kind = live_status.get("type")

            if kind == "retry":
                return "retry", run_seconds

            if kind == "busy":
                return "busy", run_seconds

        if stored == "error":
            return "error", age_seconds

        return "idle", age_seconds

    # No fresh watcher instance.
    #
    # Even an old stored IDLE is CLOSED if the OpenCode process that
    # owned it has exited. This is crucial for keeping /oc current.
    if process_state in {"dead", "reused"}:
        return "closed", age_seconds

    if stored in {"busy", "retry", "waiting"}:
        if process_state == "opencode":
            if age_seconds >= STALE_AFTER_MINUTES * 60:
                return "stale", age_seconds

            return "unknown", age_seconds

        # Legacy state with no usable PID.
        if age_seconds >= STALE_AFTER_MINUTES * 60:
            return "closed", age_seconds

        return "unknown", age_seconds

    if stored == "idle":
        # Legacy IDLE with no PID: recent = historical idle, old = closed.
        if process_state == "unknown":
            if age_seconds >= STALE_AFTER_MINUTES * 60:
                return "closed", age_seconds

            return "idle", age_seconds

        # PID is still OpenCode but watcher heartbeat is missing.
        # This is not a live-confirmed window.
        if age_seconds >= STALE_AFTER_MINUTES * 60:
            return "stale", age_seconds

        return "unknown", age_seconds

    if stored == "error":
        return "error", age_seconds

    if stored not in ICONS:
        return "unknown", age_seconds

    return stored, age_seconds


def load_rows(
    max_age_hours: int = MAX_AGE_HOURS,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    now = datetime.now(timezone.utc)
    live_instances = load_live_instances(now)
    rows: list[dict[str, Any]] = []

    for data in load_json_files(STATE_DIR):
        updated = parse_dt(data.get("updatedAt"))

        if not updated:
            continue

        age_seconds = (now - updated).total_seconds()

        if age_seconds > max_age_hours * 3600:
            continue

        instance = match_instance(data, live_instances)

        status, display_seconds = effective_status(
            data,
            instance,
            now,
        )

        row = dict(data)
        row["_updated"] = updated
        row["_status"] = status
        row["_display_seconds"] = display_seconds
        row["_instance"] = instance

        rows.append(row)

    rows.sort(
        key=lambda item: (
            PRIORITY.get(item["_status"], 99),
            -item["_updated"].timestamp(),
        )
    )

    return rows, live_instances


def build_live_windows(
    rows: list[dict[str, Any]],
    live_instances: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    One result = one currently alive OpenCode process/window.

    v3.4+ heartbeat tells us which session is currently selected/active
    in that exact process.
    """
    now = datetime.now(timezone.utc)

    rows_by_id = {
        str(row.get("sessionID")): row
        for row in rows
        if row.get("sessionID")
    }

    windows: list[dict[str, Any]] = []

    for instance in live_instances.values():
        session_id = instance.get("currentSessionID")
        session_status = (
            str(instance.get("currentSessionStatus"))
            if instance.get("currentSessionStatus")
            else None
        )

        if session_id and str(session_id) in rows_by_id:
            row = dict(rows_by_id[str(session_id)])

            # The heartbeat of THIS live process is authoritative for
            # what is currently open in the window.
            row["_instance"] = instance

            status = session_status or row.get("_status") or "idle"

            if status not in LIVE_WINDOW_STATUSES:
                status = "idle"

            row["_status"] = status

            started = parse_dt(
                row.get("turnStartedAt") or row.get("startedAt")
            )
            updated = row.get("_updated")

            if status in {"busy", "waiting", "retry"} and started:
                row["_display_seconds"] = (now - started).total_seconds()
            elif isinstance(updated, datetime):
                row["_display_seconds"] = (now - updated).total_seconds()
            else:
                row["_display_seconds"] = 0.0
                row["_updated"] = now

            windows.append(row)
            continue

        # Brand-new OpenCode window: heartbeat exists, but no session event
        # has happened yet. Still show it because it is genuinely open.
        heartbeat = instance.get("_heartbeat")
        started = parse_dt(instance.get("startedAt"))

        windows.append(
            {
                "sessionID": None,
                "instanceID": instance.get("instanceID"),
                "pid": instance.get("pid"),
                "project": instance.get("project", "?"),
                "directory": instance.get("directory"),
                "worktree": instance.get("worktree"),
                "title": instance.get("currentSessionTitle")
                or "OpenCode window is open; no task has started yet",
                "_status": "ready",
                "_updated": heartbeat
                if isinstance(heartbeat, datetime)
                else now,
                "_display_seconds": (
                    (now - started).total_seconds() if started else 0.0
                ),
                "_instance": instance,
            }
        )

    def sort_key(row: dict[str, Any]):
        order = {
            "waiting": 0,
            "error": 1,
            "retry": 2,
            "busy": 3,
            "ready": 4,
            "idle": 5,
        }

        updated = row.get("_updated")

        timestamp = (
            updated.timestamp()
            if isinstance(updated, datetime)
            else 0.0
        )

        return (
            order.get(row.get("_status"), 99),
            -timestamp,
        )

    windows.sort(key=sort_key)
    return windows


def tests_rollup(
    state: dict[str, Any],
) -> tuple[str, str]:
    tests = as_list(state.get("tests"))

    if not tests:
        return "", "not run"

    statuses = [
        str(item.get("status", "unknown"))
        for item in tests
        if isinstance(item, dict)
    ]

    if not statuses:
        return "", "not run"

    if "failed" in statuses:
        return "❌", "some failed"

    if "running" in statuses:
        return "⏳", "still running"

    if "unknown" in statuses:
        return "❔", "result unknown"

    if all(item == "passed" for item in statuses):
        return "✅", "passed"

    return "❔", "mixed status"


def diff_rollup(
    state: dict[str, Any],
) -> tuple[int, int, int, str]:
    diff = as_dict(state.get("sessionDiff"))

    if not diff.get("available"):
        return 0, 0, 0, ""

    files = safe_int(diff.get("filesCount"))
    additions = safe_int(diff.get("additions"))
    deletions = safe_int(diff.get("deletions"))

    if files <= 0:
        return 0, 0, 0, ""

    return (
        files,
        additions,
        deletions,
        f"{files}f +{additions}/-{deletions}",
    )


def row_suffix(row: dict[str, Any]) -> str:
    parts: list[str] = []

    _, _, _, diff_text = diff_rollup(row)
    test_icon, _ = tests_rollup(row)

    if diff_text:
        parts.append(diff_text)

    if test_icon:
        parts.append(f"{test_icon} tests")

    last_model = row.get("lastModel")

    if last_model:
        parts.append(
            f"🤖 {short_text(str(last_model).split('/')[-1], 24)}"
        )

    return " · " + " · ".join(parts) if parts else ""


def display_age(row: dict[str, Any]) -> str:
    status = row.get("_status", "unknown")
    value = human_duration(row.get("_display_seconds", 0))

    if status in {"busy", "waiting", "retry"}:
        return value

    return f"{value} ago"


def short_session_id(row: dict[str, Any], limit: int = 10) -> str:
    session_id = str(row.get("sessionID") or "")
    return session_id[:limit] if session_id else "—"


def select_row(
    raw_args: str,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    query = raw_args.strip()

    if not query:
        return None, None

    if query.isdigit():
        index = int(query) - 1

        if 0 <= index < len(rows):
            return rows[index], None

        return None, (
            f"No session #{query}. "
            f"Currently listed: {len(rows)}."
        )

    matches = [
        row
        for row in rows
        if str(row.get("sessionID", "")).startswith(query)
    ]

    if len(matches) == 1:
        return matches[0], None

    query_low = query.lower()

    fuzzy = [
        row
        for row in rows
        if (
            query_low in str(row.get("project", "")).lower()
            or query_low in str(row.get("title", "")).lower()
        )
    ]

    if len(fuzzy) == 1:
        return fuzzy[0], None

    if len(matches) > 1 or len(fuzzy) > 1:
        return None, (
            "Multiple matches found. "
            "Use a longer session_id prefix; /oc all lists IDs."
        )

    return None, (
        "Session not found. "
        "Open windows: /oc · history: /oc all."
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_live_windows(
    windows: list[dict[str, Any]],
) -> str:
    if not windows:
        return (
            "▣ OC · now\n\n"
            "No live OpenCode windows.\n"
            "History: /oc all · closed: /occlosed"
        )

    lines = [
        f"▣ OC · now · windows: {len(windows)}",
        "",
    ]

    for index, row in enumerate(windows, start=1):
        status = row["_status"]
        icon = ICONS.get(status, "❔")
        label = LABELS.get(status, status.upper())

        project = short_text(row.get("project", "?"), 36)
        title = short_text(row.get("title") or "untitled", 82)

        if status in {"busy", "waiting", "retry"}:
            time_text = human_duration(row.get("_display_seconds", 0))
        elif status == "ready":
            time_text = "open " + human_duration(
                row.get("_display_seconds", 0)
            )
        else:
            time_text = (
                human_duration(row.get("_display_seconds", 0)) + " ago"
            )

        lines.append(
            f"{icon} {index} · {label} · "
            f"{project} · {time_text}{row_suffix(row)}"
        )
        lines.append(f"   {title}")

        instance = as_dict(row.get("_instance"))
        pid = instance.get("pid")

        if pid:
            lines.append(f"   PID {pid}")

        lines.append("")

    lines.extend(
        [
            "Details: /oc <number>",
            "History: /oc all · closed: /occlosed",
        ]
    )

    return "\n".join(lines).rstrip()


def render_oc_list(
    rows: list[dict[str, Any]],
    include_closed: bool = False,
) -> str:
    visible_rows = (
        rows
        if include_closed
        else [row for row in rows if row["_status"] != "closed"]
    )

    if not visible_rows:
        if include_closed:
            return (
                "No OpenCode sessions found in the last "
                f"{MAX_AGE_HOURS} "
                f"{plural_ru(MAX_AGE_HOURS, 'hour', 'hours', 'hours')}."
            )

        return (
            "▣ OC · now\n\n"
            "No active or recently completed sessions.\n"
            "Closed: /occlosed"
        )

    lines = [
        (
            f"▣ OC · last {MAX_AGE_HOURS} "
            f"{plural_ru(MAX_AGE_HOURS, 'hour', 'hours', 'hours')}"
            if include_closed
            else "▣ OC · now"
        ),
        "",
    ]

    shown = visible_rows[:MAX_LIST_ROWS]

    for index, row in enumerate(shown, start=1):
        status = row["_status"]
        icon = ICONS.get(status, "❔")
        label = LABELS.get(status, status.upper())

        project = short_text(row.get("project", "?"), 36)
        title = short_text(row.get("title") or "untitled", 82)

        # History row numbers do not match live-window numbers
        # from /oc, so use session_id to select a historical session.
        marker = (
            short_session_id(row)
            if include_closed
            else str(index)
        )

        lines.append(
            f"{icon} {marker} · {label} · "
            f"{project} · {display_age(row)}{row_suffix(row)}"
        )
        lines.append(f"   {title}")

    hidden = len(visible_rows) - len(shown)

    if hidden > 0:
        lines.extend(["", f"… more: {hidden} sessions"])

    lines.append("")

    if include_closed:
        lines.append(
            "This is history. Open a session: /oc <session_id>"
        )
        lines.append(
            "Numbers in /oc refer to open windows, not this history list."
        )
    else:
        lines.append("Details: /oc <number> · closed: /occlosed")

    return "\n".join(lines)


def render_session(
    row: dict[str, Any],
) -> str:
    status = row.get("_status", "unknown")
    icon = ICONS.get(status, "❔")
    label = LABELS.get(status, status.upper())

    lines = [
        f"{icon} ▣ OC · {label}",
        "",
        f"📝 {row.get('title') or 'Untitled'}",
        f"📁 {row.get('project', '?')}",
        f"📂 {compact_path(row.get('directory'))}",
        f"⏱ {display_age(row)}",
        f"🆔 {row.get('sessionID', '?')}",
    ]

    last_model = row.get("lastModel")

    if last_model:
        lines.append(f"🤖 Model {last_model}")

    instance = as_dict(row.get("_instance"))
    pid = instance.get("pid") or row.get("pid")

    if pid and instance:
        lines.append(f"🟢 PID {pid} · heartbeat live")
    elif pid:
        lines.append(f"⚫ PID {pid} · liveness unconfirmed")

    if status == "retry":
        live = as_dict(
            as_dict(instance.get("statuses")).get(row.get("sessionID"))
        )

        attempt = live.get("attempt") or row.get("retryAttempt")

        if attempt:
            lines.append(f"🟠 Retry attempt: {attempt}")

    summary = str(row.get("lastSummary") or "").strip()

    if summary:
        lines.extend(["", "🧠 Last summary", summary[:1400]])

    diff = as_dict(row.get("sessionDiff"))

    lines.extend(["", "📦 Session diff"])

    if not diff.get("available"):
        lines.append("Unavailable")
    else:
        files = as_list(diff.get("files"))
        count = safe_int(diff.get("filesCount"))
        additions = safe_int(diff.get("additions"))
        deletions = safe_int(diff.get("deletions"))
        scope = diff.get("scope", "?")

        if count <= 0:
            lines.append("No file changes")
        else:
            lines.append(
                f"{count} {plural_ru(count, 'file', 'files', 'files')} · +{additions}/-{deletions} · {scope}"
            )

            for item in files[:12]:
                if not isinstance(item, dict):
                    continue

                status_raw = str(item.get("status", "modified"))

                file_icon = {
                    "added": "A",
                    "deleted": "D",
                }.get(status_raw, "M")

                lines.append(
                    f"{file_icon} {short_text(item.get('file'), 120)}"
                )

            # filesCount may exceed the saved file list.
            hidden = max(count, len(files)) - min(len(files), 12)

            if hidden > 0:
                lines.append(f"… more: {hidden}")

    tests = as_list(row.get("tests"))
    lines.extend(["", "🧪 Tests"])

    if not tests:
        lines.append("Tests not run")
    else:
        for test in tests[-6:]:
            if not isinstance(test, dict):
                continue

            status_raw = str(test.get("status", "unknown"))

            test_icon = {
                "passed": "✅",
                "failed": "❌",
                "running": "⏳",
                "unknown": "❔",
            }.get(status_raw, "❔")

            lines.append(
                f"{test_icon} {short_text(test.get('command'), 150)}"
            )

    return "\n".join(lines)


def render_waiting(
    rows: list[dict[str, Any]],
) -> str:
    attention_statuses = {
        "waiting",
        "error",
        "retry",
        "stale",
        "unknown",
    }

    attention = [
        row for row in rows if row["_status"] in attention_statuses
    ]

    if not attention:
        return (
            "✅ OpenCode is healthy.\n"
            "No WAITING / ERROR / RETRY / STALE / UNKNOWN sessions."
        )

    lines = [f"⚠️ Need attention: {len(attention)}", ""]

    for row in attention[:12]:
        status = row["_status"]
        icon = ICONS.get(status, "❔")

        lines.append(
            f"{icon} {LABELS.get(status, status.upper())} "
            f"· {row.get('project', '?')} "
            f"· {display_age(row)}"
        )
        lines.append(
            f"   {short_text(row.get('title') or 'untitled', 90)}"
        )
        lines.append(f"   {short_session_id(row, 32)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def render_today(
    rows: list[dict[str, Any]],
) -> str:
    local_now = datetime.now().astimezone()
    today = local_now.date()

    today_rows = []

    for row in rows:
        updated = row.get("_updated")

        if not isinstance(updated, datetime):
            continue

        if updated.astimezone().date() == today:
            today_rows.append(row)

    if not today_rows:
        return "No OpenCode sessions recorded today."

    counts: dict[str, int] = {}

    total_files = 0
    total_additions = 0
    total_deletions = 0

    test_passed = 0
    test_failed = 0
    test_unknown = 0
    test_running = 0

    for row in today_rows:
        status = row["_status"]
        counts[status] = counts.get(status, 0) + 1

        diff = as_dict(row.get("sessionDiff"))

        if diff.get("available"):
            total_files += safe_int(diff.get("filesCount"))
            total_additions += safe_int(diff.get("additions"))
            total_deletions += safe_int(diff.get("deletions"))

        for test in as_list(row.get("tests")):
            if not isinstance(test, dict):
                continue

            value = test.get("status")

            if value == "passed":
                test_passed += 1
            elif value == "failed":
                test_failed += 1
            elif value == "running":
                test_running += 1
            else:
                test_unknown += 1

    idle = counts.get("idle", 0)
    closed = counts.get("closed", 0)

    lines = [
        f"📊 ▣ OC · {today.strftime('%d/%m/%Y')}",
        "",
        f"Sessions: {len(today_rows)}",
        # idle and closed both represent completed sessions;
        # the difference is whether the OpenCode window is still alive.
        f"⚪️ Completed: {idle + closed} (window open: {idle} · closed: {closed})",
        f"🟡 Busy: {counts.get('busy', 0)}",
        f"🔐 Waiting: {counts.get('waiting', 0)}",
        f"🟠 Retry: {counts.get('retry', 0)}",
        f"🔴 Errors: {counts.get('error', 0)}",
        f"💤 Stale: {counts.get('stale', 0)}",
        f"❔ Unknown: {counts.get('unknown', 0)}",
    ]

    turn_block = today_turns_block()

    if turn_block:
        # The turn log is more accurate: the legacy block only counts the LAST
        # saved turn of each session. Two different totals in one report
        # are less useful than a single accurate total.
        lines.extend(["", *turn_block])
    else:
        lines.extend(
            [
                "",
                "📦 Last saved diff of each session",
                f"{total_files} files · +{total_additions}/-{total_deletions}",
                "",
                "🧪 Tests in the last saved turns",
                f"✅ {test_passed} · ❌ {test_failed} · "
                f"❔ {test_unknown} · ⏳ {test_running}",
                "",
                "ℹ️ Full daily totals require hermes-watch v3.6+",
            ]
        )

    lines.extend(["", "Recent sessions:"])

    recent = sorted(
        today_rows,
        key=lambda row: row["_updated"],
        reverse=True,
    )[:6]

    for row in recent:
        local_time = row["_updated"].astimezone().strftime("%H:%M")
        icon = ICONS.get(row["_status"], "❔")

        lines.append(
            f"{local_time} {icon} "
            f"{short_text(row.get('title') or row.get('project'), 60)}"
        )

    lines.extend(
        [
            "",
            "Period: /ocstats N · projects: /ocproj · models: /models",
        ]
    )

    return "\n".join(lines)


def today_turns_block() -> list[str]:
    """
    Daily totals from the turn log. The legacy snapshot only contains the
    last saved turn of each session, so it misses multiple completed turns.
    """
    local_now = datetime.now().astimezone()
    start_of_day = local_now.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    turns = iter_turns(load_all_states(), start_of_day)

    if not turns:
        return []

    seconds = 0.0
    files = additions = deletions = 0
    passed = failed = 0
    cost = 0.0
    has_usage = False
    projects: set[str] = set()

    for state, turn, _ in turns:
        seconds += safe_int(turn.get("durationMs")) / 1000
        files += safe_int(turn.get("files"))
        additions += safe_int(turn.get("additions"))
        deletions += safe_int(turn.get("deletions"))
        passed += safe_int(turn.get("testsPassed"))
        failed += safe_int(turn.get("testsFailed"))
        projects.add(str(state.get("project", "?")))

        if turn.get("cost") is not None:
            has_usage = True
            cost += float(turn.get("cost") or 0)

    block = [
        "🧾 Today's turn log",
        f"Turns: {len(turns)} · projects: {len(projects)} · "
        f"time: {human_duration(seconds)}",
        f"Changes: {files} {plural_ru(files, 'file', 'files', 'files')} · +{additions}/-{deletions}",
        f"Tests: ✅ {passed} · ❌ {failed}",
    ]

    if has_usage:
        block.append(f"Cost: {format_cost(cost)}")

    return block


def render_errors(
    rows: list[dict[str, Any]],
) -> str:
    problem_statuses = {
        "error",
        "retry",
        "stale",
        "unknown",
        "waiting",
    }

    problems = [
        row for row in rows if row["_status"] in problem_statuses
    ]

    problems.sort(key=lambda row: row["_updated"], reverse=True)

    if not problems:
        return (
            "✅ No problematic "
            "OpenCode states found in the last 24 hours."
        )

    lines = ["🔴 ▣ OC · recent problems", ""]

    for row in problems[:10]:
        status = row["_status"]
        local_time = row["_updated"].astimezone().strftime("%H:%M")

        lines.append(
            f"{local_time} "
            f"{ICONS.get(status, '❔')} "
            f"{LABELS.get(status, status.upper())}"
        )
        lines.append(
            f"{row.get('project', '?')} · "
            f"{short_text(row.get('title') or 'untitled', 85)}"
        )

        if status == "retry":
            instance = as_dict(row.get("_instance"))
            live = as_dict(
                as_dict(instance.get("statuses")).get(row.get("sessionID"))
            )

            message = live.get("message")

            if message:
                lines.append(f"↳ {short_text(message, 160)}")

        lines.append(short_session_id(row, 40))
        lines.append("")

    lines.append("Details: /oc <session_id>")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# System diagnostics
# ---------------------------------------------------------------------------

def cpu_percent() -> float | None:
    system = system_name()

    if system == "linux":
        def read_proc_cpu():
            try:
                first = (
                    Path("/proc/stat")
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                    .split()
                )
                values = [int(value) for value in first[1:]]
                idle = values[3] + (
                    values[4] if len(values) > 4 else 0
                )
                total = sum(values)
                return total, idle
            except Exception:
                return None

        first = read_proc_cpu()
        if not first:
            return None

        time.sleep(0.15)
        second = read_proc_cpu()
        if not second:
            return None

        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]

        if total_delta <= 0:
            return None

        return max(
            0.0,
            min(100.0, 100.0 * (1.0 - idle_delta / total_delta)),
        )

    if system == "darwin":
        # Sum process CPU and normalize to the whole machine = 100%.
        code, stdout, _ = run_command(
            ["ps", "-A", "-o", "%cpu="],
            timeout=5,
        )
        if code != 0:
            return None

        total = 0.0
        for line in stdout.splitlines():
            try:
                total += float(line.strip().replace(",", "."))
            except Exception:
                continue

        cpus = os.cpu_count() or 1
        return max(0.0, min(100.0, total / cpus))

    return None


def memory_info() -> tuple[int, int] | None:
    system = system_name()

    if system == "linux":
        try:
            values: dict[str, int] = {}

            for line in (
                Path("/proc/meminfo")
                .read_text(encoding="utf-8")
                .splitlines()
            ):
                if ":" not in line:
                    continue

                key, raw = line.split(":", 1)
                parts = raw.strip().split()

                if not parts or not parts[0].isdigit():
                    continue

                values[key] = int(parts[0]) * 1024

            total = values.get("MemTotal", 0)

            if total <= 0:
                return None

            available = values.get(
                "MemAvailable",
                values.get("MemFree", 0),
            )
            return max(0, total - available), total
        except Exception:
            return None

    if system == "darwin":
        code, total_out, _ = run_command(
            ["sysctl", "-n", "hw.memsize"],
            timeout=5,
        )
        if code != 0:
            return None

        try:
            total = int(total_out.strip())
        except Exception:
            return None

        if total <= 0:
            return None

        code, vm_out, _ = run_command(["vm_stat"], timeout=5)
        if code != 0 or not vm_out:
            return None

        page_size = 4096
        first_line = vm_out.splitlines()[0]
        match = re.search(r"page size of\s+(\d+)\s+bytes", first_line)
        if match:
            page_size = int(match.group(1))

        stats: dict[str, int] = {}
        for line in vm_out.splitlines()[1:]:
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            raw = raw.strip().rstrip(".")
            try:
                stats[key.strip()] = int(raw)
            except Exception:
                continue

        # Approximation suitable for a status widget.
        available = (
            stats.get("Pages free", 0)
            + stats.get("Pages speculative", 0)
            + stats.get("Pages inactive", 0)
            + stats.get("Pages purgeable", 0)
        ) * page_size

        available = min(total, max(0, available))
        return total - available, total

    return None


def human_bytes(value: int) -> str:
    number = float(value)

    for suffix in ["B", "KB", "MB", "GB", "TB"]:
        if abs(number) < 1024.0:
            if suffix in {"GB", "TB"}:
                return f"{number:.1f} {suffix}"
            return f"{number:.0f} {suffix}"
        number /= 1024.0

    return f"{number:.1f} PB"


def uptime_seconds() -> float | None:
    system = system_name()

    if system == "linux":
        try:
            return float(
                Path("/proc/uptime")
                .read_text(encoding="utf-8")
                .split()[0]
            )
        except Exception:
            return None

    if system == "darwin":
        code, stdout, _ = run_command(
            ["sysctl", "-n", "kern.boottime"],
            timeout=5,
        )
        if code != 0:
            return None

        match = re.search(r"sec\s*=\s*(\d+)", stdout)
        if not match:
            return None

        return max(0.0, time.time() - int(match.group(1)))

    return None


def process_counts() -> tuple[int, int]:
    """Use one shared process snapshot instead of a separate scan."""
    opencode = 0
    hermes = 0

    for command in process_table().values():
        if re.search(r"(^|[/\s])opencode(\s|$)", command):
            opencode += 1

        if re.search(r"(^|[/\s])hermes(\s|$)", command):
            hermes += 1

    return opencode, hermes


def render_system() -> str:
    cpu = cpu_percent()
    mem = memory_info()
    uptime = uptime_seconds()

    try:
        disk = shutil.disk_usage("/")
    except Exception:
        disk = None

    try:
        load1, load5, load15 = os.getloadavg()
        load_text = f"{load1:.2f} / {load5:.2f} / {load15:.2f}"
    except Exception:
        load_text = "n/a"

    opencode_count, hermes_count = process_counts()

    live_instances = load_live_instances(
        datetime.now(timezone.utc)
    )

    os_label = platform.system() or "Unknown"
    machine = platform.machine() or "?"

    lines = [f"🖥 Workstation · {os_label} {machine}", ""]

    lines.append(
        f"CPU     {cpu:.0f}%" if cpu is not None else "CPU     n/a"
    )

    if mem:
        used, total = mem
        lines.append(
            f"RAM     {human_bytes(used)} / {human_bytes(total)}"
        )
    else:
        lines.append("RAM     n/a")

    if disk and disk.total > 0:
        lines.append(
            f"Disk /  {human_bytes(disk.used)} / "
            f"{human_bytes(disk.total)} "
            f"({disk.used / disk.total * 100:.0f}%)"
        )
    else:
        lines.append("Disk /  n/a")

    lines.append(f"Load    {load_text}")

    lines.append(
        f"Uptime  {human_duration(uptime)}"
        if uptime is not None
        else "Uptime  n/a"
    )

    lines.extend(
        [
            "",
            f"OpenCode processes: {opencode_count}",
            f"OpenCode live watcher instances: {len(live_instances)}",
            f"Hermes-related processes: {hermes_count}",
        ]
    )

    return "\n".join(lines)


def watcher_path_candidates() -> list[Path]:
    candidates = [
        OPENCODE_PLUGIN_DIR / "hermes-watch.ts",
        HERMES_HOME / "plugins" / "hermes-watch.ts",
    ]

    try:
        candidates.extend(
            sorted(OPENCODE_PLUGIN_DIR.glob("hermes-watch*.ts"))
        )
    except Exception:
        pass

    return candidates


def watcher_version() -> str:
    for path in watcher_path_candidates():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        match = re.search(
            r'WATCHER_VERSION\s*=\s*["\']([^"\']+)["\']',
            text,
        )

        if match:
            return match.group(1)

        return "installed"

    return "not found"


def process_env(pid: Any, key: str) -> str | None:
    # Linux-only fallback for old watcher instance files.
    if system_name() != "linux":
        return None

    if not isinstance(pid, int):
        return None

    try:
        raw = (
            Path(f"/proc/{pid}/environ").read_bytes().split(b"\x00")
        )

        prefix = (key + "=").encode()

        for item in raw:
            if item.startswith(prefix):
                return item[len(prefix):].decode(
                    "utf-8", errors="replace"
                )
    except Exception:
        pass

    return None


def summary_model_from_instances(
    live_instances: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    # v3.2+ watcher persists these directly in heartbeat JSON.
    for instance in live_instances.values():
        provider = instance.get("summaryProvider")
        model = instance.get("summaryModel")

        if provider or model:
            return (
                str(provider) if provider else None,
                str(model) if model else None,
            )

    # Backward-compatible Linux fallback for v3.1 heartbeat files.
    for instance in live_instances.values():
        pid = instance.get("pid")

        provider = process_env(
            pid, "OPENCODE_HERMES_SUMMARY_PROVIDER"
        )
        model = process_env(pid, "OPENCODE_HERMES_SUMMARY_MODEL")

        if provider or model:
            return provider, model

    return None, None


def get_main_model() -> str:
    code, stdout, _ = run_command(
        ["hermes", "config", "get", "model", "--json"],
        timeout=6,
    )

    if code != 0 or not stdout:
        return "unknown"

    try:
        data = json.loads(stdout)

        if isinstance(data, str):
            return data

        if isinstance(data, dict):
            provider = data.get("provider") or data.get("backend")
            model = data.get("default") or data.get("model")

            if provider and model:
                return f"{provider}/{model}"

            if model:
                return str(model)

        return short_text(stdout, 100)
    except Exception:
        return short_text(stdout, 100)


def render_hstatus() -> str:
    now = datetime.now(timezone.utc)
    live_instances = load_live_instances(now)

    version_code, version_out, _ = run_command(
        ["hermes", "--version"],
        timeout=5,
    )

    gateway_code, gateway_out, gateway_err = run_command(
        ["hermes", "gateway", "status"],
        timeout=8,
    )

    gateway_ok = gateway_code == 0 and bool(gateway_out)

    summary_provider, summary_model = summary_model_from_instances(
        live_instances
    )

    live_watcher = next(
        (
            str(item.get("watcherVersion"))
            for item in live_instances.values()
            if item.get("watcherVersion")
        ),
        watcher_version(),
    )

    lines = [
        "🪽 Hermes / OpenCode Control",
        "",
        (
            f"Hermes       {version_out}"
            if version_code == 0 and version_out
            else "Hermes       version unknown"
        ),
        f"Gateway      {'✅' if gateway_ok else '❌'}",
        f"Main model   {get_main_model()}",
        f"Watcher      {live_watcher}",
        f"Control      v{PLUGIN_VERSION}",
        f"OC live      {len(live_instances)}",
    ]

    if summary_provider or summary_model:
        lines.append(
            "Summary      "
            f"{summary_provider or 'default'}/"
            f"{summary_model or 'default'}"
        )
    else:
        lines.append("Summary      no live OpenCode env detected")

    lines.append(f"Notify       {mute_summary()}")

    levels = next(
        (
            as_list(item.get("notifyLevels"))
            for item in live_instances.values()
            if item.get("notifyLevels")
        ),
        [],
    )

    if levels:
        lines.append("Levels       " + ", ".join(str(x) for x in levels))

    # The watcher reads control.json itself; report if it has not acknowledged it yet.
    remaining, _ = mute_state()
    watcher_sees_mute = any(
        item.get("muteUntil") for item in live_instances.values()
    )

    if remaining > 0 and live_instances and not watcher_sees_mute:
        lines.append(
            "⚠️ mute is set, but no live watcher has acknowledged it "
            "(requires hermes-watch v3.6+)"
        )

    if gateway_out:
        useful = [
            line.strip()
            for line in gateway_out.splitlines()
            if line.strip()
        ][:8]

        if useful:
            lines.extend(["", "Gateway:", *useful])
    elif gateway_err:
        lines.extend(
            ["", f"Gateway error: {short_text(gateway_err, 350)}"]
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------

def handle_oc(raw_args: str) -> str:
    rows, live_instances = load_rows()

    query = raw_args.strip()

    windows = build_live_windows(rows, live_instances)

    if not query:
        return render_live_windows(windows)

    if query.lower() in {"all", "\u0432\u0441\u0435", "history"}:
        return render_oc_list(rows, include_closed=True)

    # Numeric indices now refer to actual live OpenCode windows.
    if query.isdigit():
        index = int(query) - 1

        if not (0 <= index < len(windows)):
            if not windows:
                return (
                    "No OpenCode windows are open.\n"
                    "History: /oc all · closed: /occlosed"
                )

            return (
                f"No open window #{query}. "
                f"Currently open: {len(windows)}."
            )

        row = windows[index]

        if not row.get("sessionID"):
            instance = as_dict(row.get("_instance"))

            return "\n".join(
                [
                    "🟢 ▣ OC · OPEN",
                    "",
                    f"📁 {row.get('project', '?')}",
                    f"📂 {compact_path(row.get('directory'))}",
                    f"🟢 PID {instance.get('pid', '?')} · heartbeat live",
                    "",
                    "The current session has not been recorded yet.",
                    "Start a task in this window; the watcher will pick it up.",
                ]
            )

        return render_session(row)

    # Explicit session-id/title lookup is still allowed across history.
    row, error = select_row(query, rows)

    if error:
        return error

    if row is None:
        return "Session not found."

    return render_session(row)


def handle_occlosed(_raw_args: str) -> str:
    rows, _instances = load_rows()

    closed = [row for row in rows if row["_status"] == "closed"]

    closed.sort(key=lambda row: row["_updated"], reverse=True)

    if not closed:
        return (
            "⚫️ No CLOSED sessions found in the last "
            f"{MAX_AGE_HOURS} "
            f"{plural_ru(MAX_AGE_HOURS, 'hour', 'hours', 'hours')}."
        )

    limit = 15

    lines = [f"⚫️ Closed OpenCode sessions: {len(closed)}", ""]

    for row in closed[:limit]:
        updated = row["_updated"].astimezone().strftime("%H:%M")

        lines.append(
            f"⚫️ {updated} · {row.get('project', '?')} "
            f"· {display_age(row)} · {short_session_id(row)}"
        )
        lines.append(
            f"   {short_text(row.get('title') or 'untitled', 88)}"
        )
        lines.append("")

    hidden = len(closed) - limit

    if hidden > 0:
        lines.append(f"… more: {hidden}")
        lines.append("")

    lines.extend(
        [
            "CLOSED = this session's OpenCode process is no longer running.",
            "The session is not stuck. Details: /oc <session_id>",
        ]
    )

    return "\n".join(lines)


def handle_oclast(_raw_args: str) -> str:
    rows, _instances = load_rows()

    # v1.4 only showed IDLE, so closing the window meant
    # /oclast could no longer find the work that had just finished.
    finished = [
        row
        for row in rows
        if row["_status"] in {"idle", "closed"}
    ]

    with_result = [
        row
        for row in finished
        if row.get("lastSummary") or row.get("sessionDiff")
    ]

    candidates = with_result or finished

    if not candidates:
        return (
            "No completed OpenCode sessions in the last "
            f"{MAX_AGE_HOURS} "
            f"{plural_ru(MAX_AGE_HOURS, 'hour', 'hours', 'hours')}."
        )

    row = max(candidates, key=lambda item: item["_updated"])

    header = (
        "✅ Last completed session"
        if row["_status"] == "idle"
        else "✅ Last completed session (window already closed)"
    )

    return f"{header}\n\n{render_session(row)}"


def handle_ocwait(_raw_args: str) -> str:
    rows, _instances = load_rows()
    return render_waiting(rows)


def handle_today(_raw_args: str) -> str:
    # Use 48h so a local-time day remains complete around UTC boundary.
    rows, _instances = load_rows(max_age_hours=48)
    return render_today(rows)


def handle_errors(_raw_args: str) -> str:
    rows, _instances = load_rows()
    return render_errors(rows)


def handle_sys(_raw_args: str) -> str:
    return render_system()


def handle_hstatus(_raw_args: str) -> str:
    return render_hstatus()


def handle_models(raw_args: str) -> str:
    """
    /models       -> last 1 day
    /models 7     -> last 7 days

    Uses OpenCode's own stats command, so this is usage recorded by
    OpenCode rather than an estimate from watcher state.
    """
    raw = raw_args.strip()

    if raw:
        if not raw.isdigit():
            return (
                "Usage: /models [days]\n"
                "Examples: /models · /models 7 · /models 30"
            )
        days = int(raw)
    else:
        days = 1

    if days < 1 or days > 90:
        return "Choose a period from 1 to 90 days."

    code, stdout, stderr = run_command(
        ["opencode", "stats", "--days", str(days), "--models", "20"],
        timeout=20,
    )

    if code != 0:
        return (
            "❌ Could not get OpenCode model stats:\n"
            + short_text(stderr or stdout or "unknown error", 1000)
        )

    clean = strip_ansi(stdout).strip()

    if not clean:
        return (
            f"🤖 OpenCode models · {days}d\n\n"
            "OpenCode returned no statistics."
        )

    # Telegram has a finite message size; keep command response compact.
    max_body = 3400
    if len(clean) > max_body:
        clean = clean[:max_body].rstrip() + "\n…"

    period = (
        "today / 1 day"
        if days == 1
        else f"last {days} {plural_ru(days, 'day', 'days', 'days')}"
    )

    return (
        f"🤖 ▣ OC · models · {period}\n\n"
        f"{clean}\n\n"
        "Period: /models N"
    )


def handle_notifytest(_raw_args: str) -> str:
    message = (
        "✅ OpenCode Control: proactive Hermes → Telegram delivery works"
    )

    code, stdout, stderr = run_command(
        ["hermes", "send", "--to", "telegram", "--quiet", message],
        timeout=12,
    )

    if code == 0:
        return (
            "✅ Test sent as a separate proactive message.\n"
            "If it arrived, the hermes send → Telegram delivery path works."
        )

    return (
        "❌ hermes send failed:\n"
        + short_text(stderr or stdout, 700)
    )


# ---------------------------------------------------------------------------
# Turn log, control file, target resolution
# ---------------------------------------------------------------------------

def load_all_states() -> list[dict[str, Any]]:
    """
    Load all retained state without the MAX_AGE_HOURS window. /oc shows live
    activity; /ocstats and /ocfind use history not yet removed by the watcher.
    """
    states: list[dict[str, Any]] = []

    for data in load_json_files(STATE_DIR):
        updated = parse_dt(data.get("updatedAt"))

        if not updated:
            continue

        data["_updated"] = updated
        states.append(data)

    return states


def iter_turns(
    states: list[dict[str, Any]],
    since: datetime | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any], datetime]]:
    """(state, turn, finished_at) from the hermes-watch v3.6+ turn log."""
    result: list[tuple[dict[str, Any], dict[str, Any], datetime]] = []

    for state in states:
        for turn in as_list(state.get("turns")):
            if not isinstance(turn, dict):
                continue

            finished = parse_dt(turn.get("finishedAt"))

            if not finished:
                continue

            if since and finished < since:
                continue

            result.append((state, turn, finished))

    result.sort(key=lambda item: item[2])
    return result


def format_tokens(value: float | int) -> str:
    value = float(value or 0)

    if value <= 0:
        return "0"
    if value < 1000:
        return str(int(round(value)))
    if value < 1_000_000:
        return f"{value / 1000:.1f}k"

    return f"{value / 1_000_000:.2f}M"


def format_cost(value: float | int) -> str:
    value = float(value or 0)

    if value <= 0:
        return "$0"
    if value < 0.01:
        return f"${value:.4f}"

    return f"${value:.2f}"


def read_control() -> dict[str, Any]:
    try:
        return as_dict(
            json.loads(CONTROL_PATH.read_text(encoding="utf-8"))
        )
    except Exception:
        return {}


def write_control(control: dict[str, Any]) -> str | None:
    """Return an error message or None."""
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)

        control = dict(control)
        control["updatedAt"] = (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        control["updatedBy"] = f"opencode-control/{PLUGIN_VERSION}"

        tmp = CONTROL_PATH.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(control, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, CONTROL_PATH)
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def mute_state() -> tuple[int, list[str]]:
    """(seconds until mute expires, disabled levels)."""
    control = read_control()

    remaining = 0
    until = parse_dt(control.get("muteUntil"))

    if until:
        remaining = max(
            0,
            int((until - datetime.now(timezone.utc)).total_seconds()),
        )

    disabled = [
        str(item).lower()
        for item in as_list(control.get("disabledLevels"))
    ]

    return remaining, disabled


def mute_summary() -> str:
    remaining, disabled = mute_state()

    parts: list[str] = []

    if remaining > 0:
        parts.append(f"muted for another {human_duration(remaining)}")

    if disabled:
        parts.append("disabled: " + ", ".join(sorted(disabled)))

    return " · ".join(parts) if parts else "notifications enabled"


def resolve_target(
    raw_args: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Resolve targets for /ocsum, /ocdiff, and /octests.

    Empty: current live window, otherwise the last completed session.
    Number: the Nth open window, as listed by /oc.
    Other: session_id, project, or title.
    """
    rows, live_instances = load_rows()
    query = raw_args.strip()

    windows = build_live_windows(rows, live_instances)

    if not query:
        for window in windows:
            if window.get("sessionID"):
                return window, None

        finished = [
            row for row in rows if row["_status"] in {"idle", "closed"}
        ]

        if finished:
            return max(finished, key=lambda row: row["_updated"]), None

        return None, (
            "No open windows or completed sessions.\n"
            "List: /oc · history: /oc all"
        )

    if query.isdigit():
        index = int(query) - 1

        if not (0 <= index < len(windows)):
            return None, (
                f"No open window #{query}. "
                f"Currently open: {len(windows)}."
            )

        row = windows[index]

        if not row.get("sessionID"):
            return None, (
                f"Window #{query} has not started a task yet."
            )

        return row, None

    return select_row(query, rows)


def session_header(row: dict[str, Any]) -> str:
    status = row.get("_status", "unknown")

    return (
        f"{ICONS.get(status, '❔')} {row.get('project', '?')} · "
        f"{short_text(row.get('title') or 'untitled', 70)}"
    )


# ---------------------------------------------------------------------------
# New command handlers
# ---------------------------------------------------------------------------

def handle_ochelp(_raw_args: str) -> str:
    lines = [
        f"🧭 OpenCode Control v{PLUGIN_VERSION}",
        "",
    ]

    for command in COMMANDS:
        hint = command.get("args_hint")
        name = f"/{command['name']}" + (f" {hint}" if hint else "")
        lines.append(f"{name}")
        lines.append(f"   {command['description']}")

    lines.extend(
        [
            "",
            "target = a window number from /oc, session_id, or empty "
            "(current/last session).",
        ]
    )

    return "\n".join(lines)


def handle_ocsum(raw_args: str) -> str:
    row, error = resolve_target(raw_args)

    if error:
        return error

    if row is None:
        return "Session not found."

    summary = str(row.get("lastSummary") or "").strip()

    lines = [session_header(row), ""]

    if summary:
        lines.append(summary[:1500])
    else:
        lines.append("No summary saved yet (no turn has completed).")

    files, additions, deletions, _ = diff_rollup(row)

    if files:
        lines.append("")
        lines.append(f"📦 {files} {plural_ru(files, 'file', 'files', 'files')} · +{additions}/-{deletions}")

    _, tests_text = tests_rollup(row)
    lines.append(f"🧪 Tests: {tests_text}")

    turns = as_list(row.get("turns"))

    if turns:
        last = as_dict(turns[-1])
        cost = last.get("cost")

        if cost:
            lines.append(
                f"💰 {format_cost(cost)} · "
                f"{format_tokens(last.get('tokensIn', 0))} in / "
                f"{format_tokens(last.get('tokensOut', 0))} out"
            )

    lines.append("")
    lines.append(f"🆔 {row.get('sessionID', '?')} · details: /oc <id>")

    return "\n".join(lines)


def handle_ocdiff(raw_args: str) -> str:
    row, error = resolve_target(raw_args)

    if error:
        return error

    if row is None:
        return "Session not found."

    diff = as_dict(row.get("sessionDiff"))

    if not diff.get("available"):
        return (
            f"{session_header(row)}\n\n"
            "📦 Session diff unavailable.\n"
            + short_text(diff.get("error"), 300)
        )

    count = safe_int(diff.get("filesCount"))

    if count <= 0:
        return (
            f"{session_header(row)}\n\n"
            "📦 No file changes in the last turn."
        )

    files = [
        item for item in as_list(diff.get("files")) if isinstance(item, dict)
    ]

    scope = (
        "current turn"
        if diff.get("scope") == "turn"
        else "whole session"
    )

    lines = [
        session_header(row),
        "",
        f"📦 {count} {plural_ru(count, 'file', 'files', 'files')} · +{safe_int(diff.get('additions'))}"
        f"/-{safe_int(diff.get('deletions'))} · {scope}",
        "",
    ]

    limit = 40

    for item in files[:limit]:
        status_raw = str(item.get("status", "modified"))
        icon = {"added": "A", "deleted": "D"}.get(status_raw, "M")

        lines.append(
            f"{icon} {short_text(item.get('file'), 90)} "
            f"(+{safe_int(item.get('additions'))}"
            f"/-{safe_int(item.get('deletions'))})"
        )

    hidden = max(count, len(files)) - min(len(files), limit)

    if hidden > 0:
        lines.append(f"… more: {hidden}")

    if diff.get("truncated"):
        lines.append("")
        lines.append(
            "⚠️ The watcher saved only the largest changes."
        )

    return "\n".join(lines)


def handle_octests(raw_args: str) -> str:
    row, error = resolve_target(raw_args)

    if error:
        return error

    if row is None:
        return "Session not found."

    tests = [
        item for item in as_list(row.get("tests")) if isinstance(item, dict)
    ]

    if not tests:
        return (
            f"{session_header(row)}\n\n"
            "🧪 Tests were not run in the last turn."
        )

    lines = [session_header(row), "", "🧪 Test runs in the last turn", ""]

    for test in tests:
        status_raw = str(test.get("status", "unknown"))

        icon = {
            "passed": "✅",
            "failed": "❌",
            "running": "⏳",
            "unknown": "❔",
        }.get(status_raw, "❔")

        details = []

        exit_code = test.get("exitCode")
        if exit_code is not None:
            details.append(f"exit {exit_code}")

        duration = test.get("durationMs")
        if duration:
            details.append(human_duration(int(duration) / 1000))

        suffix = f" · {' · '.join(details)}" if details else ""

        lines.append(f"{icon} {short_text(test.get('command'), 120)}{suffix}")

    turns = as_list(row.get("turns"))

    if turns:
        passed = sum(safe_int(as_dict(t).get("testsPassed")) for t in turns)
        failed = sum(safe_int(as_dict(t).get("testsFailed")) for t in turns)
        unknown = sum(
            safe_int(as_dict(t).get("testsUnknown")) for t in turns
        )

        lines.extend(
            [
                "",
                f"Entire session: ✅ {passed} · ❌ {failed} · ❔ {unknown}",
            ]
        )

    return "\n".join(lines)


def handle_ocfind(raw_args: str) -> str:
    query = raw_args.strip().lower()

    if len(query) < 2:
        return (
            "Usage: /ocfind <text>\n"
            "Search by title, project, summary, and changed files."
        )

    matches: list[tuple[datetime, str]] = []

    for state in load_all_states():
        haystack_parts = [
            str(state.get("title") or ""),
            str(state.get("project") or ""),
            str(state.get("directory") or ""),
            str(state.get("lastSummary") or ""),
        ]

        for turn in as_list(state.get("turns")):
            haystack_parts.append(str(as_dict(turn).get("summary") or ""))

        hit_files = [
            str(as_dict(item).get("file") or "")
            for item in as_list(
                as_dict(state.get("sessionDiff")).get("files")
            )
        ]

        haystack = " ".join(haystack_parts + hit_files).lower()

        if query not in haystack:
            continue

        matched_file = next(
            (item for item in hit_files if query in item.lower()),
            None,
        )

        updated = state.get("_updated")

        line = (
            f"{updated.astimezone().strftime('%d/%m %H:%M')} · "
            f"{state.get('project', '?')} · "
            f"{short_text(state.get('title') or 'untitled', 60)}"
        )

        detail = f"   🆔 {str(state.get('sessionID') or '')[:12]}"

        if matched_file:
            detail += f" · 📄 {short_text(matched_file, 60)}"

        matches.append((updated, f"{line}\n{detail}"))

    if not matches:
        return f'No matches for "{raw_args.strip()}".'

    matches.sort(key=lambda item: item[0], reverse=True)

    limit = 10

    lines = [
        f"🔎 Found: {len(matches)}",
        "",
        *[text for _, text in matches[:limit]],
    ]

    if len(matches) > limit:
        lines.append("")
        lines.append(f"… more: {len(matches) - limit}")

    lines.append("")
    lines.append("Open: /oc <session_id> · summary: /ocsum <session_id>")

    return "\n".join(lines)


def handle_ocproj(raw_args: str) -> str:
    query = raw_args.strip().lower()
    states = load_all_states()

    if query:
        selected = [
            state
            for state in states
            if query in str(state.get("project", "")).lower()
        ]

        if not selected:
            return f'Project "{raw_args.strip()}" not found in watcher state.'

        selected.sort(key=lambda item: item["_updated"], reverse=True)

        lines = [
            f"📁 {selected[0].get('project', '?')} · "
            f"sessions: {len(selected)}",
            "",
        ]

        for state in selected[:12]:
            updated = state["_updated"].astimezone().strftime("%d/%m %H:%M")
            turns = as_list(state.get("turns"))

            lines.append(
                f"{updated} · {short_text(state.get('title') or 'untitled', 62)}"
            )
            lines.append(
                f"   🆔 {str(state.get('sessionID') or '')[:12]}"
                + (f" · turns: {len(turns)}" if turns else "")
            )

        return "\n".join(lines)

    since = datetime.now(timezone.utc) - timedelta(days=7)
    turns = iter_turns(states, since)

    if not turns:
        return (
            "The turn log is empty.\n"
            "Requires hermes-watch v3.6+, which writes turns[] to state."
        )

    rollup: dict[str, dict[str, float]] = {}

    for state, turn, _ in turns:
        project = str(state.get("project", "?"))
        item = rollup.setdefault(
            project,
            {"turns": 0, "seconds": 0.0, "lines": 0, "cost": 0.0},
        )

        item["turns"] += 1
        item["seconds"] += safe_int(turn.get("durationMs")) / 1000
        item["lines"] += safe_int(turn.get("additions")) + safe_int(
            turn.get("deletions")
        )
        item["cost"] += float(turn.get("cost") or 0)

    ordered = sorted(
        rollup.items(),
        key=lambda item: item[1]["turns"],
        reverse=True,
    )

    lines = ["📁 Projects · last 7 days", ""]

    for project, item in ordered[:12]:
        cost = (
            f" · {format_cost(item['cost'])}" if item["cost"] > 0 else ""
        )

        lines.append(
            f"{short_text(project, 30)} · "
            f"{int(item['turns'])} "
            f"{plural_ru(int(item['turns']), 'turn', 'turns', 'turns')} · "
            f"{human_duration(item['seconds'])} · "
            f"{int(item['lines'])} lines{cost}"
        )

    lines.append("")
    lines.append("Project details: /ocproj <name>")

    return "\n".join(lines)


def handle_ocstats(raw_args: str) -> str:
    raw = raw_args.strip()

    if raw and not raw.isdigit():
        return "Usage: /ocstats [days] · example: /ocstats 7"

    days = int(raw) if raw else 7

    if days < 1 or days > 90:
        return "Choose a period from 1 to 90 days."

    since = datetime.now(timezone.utc) - timedelta(days=days)
    states = load_all_states()
    turns = iter_turns(states, since)

    if not turns:
        return (
            "📊 No completed turns found in the last "
            f"{days} "
            f"{plural_ru(days, 'day', 'days', 'days')}.\n\n"
            "Watchers older than v3.6 do not write a turn log; "
            "use /models for model spending."
        )

    sessions = {str(state.get("sessionID")) for state, _, _ in turns}
    projects: dict[str, int] = {}
    models: dict[str, int] = {}
    tools: dict[str, int] = {}

    seconds = 0.0
    files = additions = deletions = 0
    passed = failed = unknown = 0
    errors = 0
    cost = 0.0
    tokens_in = tokens_out = 0
    has_usage = False

    for state, turn, _ in turns:
        seconds += safe_int(turn.get("durationMs")) / 1000
        files += safe_int(turn.get("files"))
        additions += safe_int(turn.get("additions"))
        deletions += safe_int(turn.get("deletions"))
        passed += safe_int(turn.get("testsPassed"))
        failed += safe_int(turn.get("testsFailed"))
        unknown += safe_int(turn.get("testsUnknown"))

        if turn.get("outcome") == "error":
            errors += 1

        if turn.get("cost") is not None:
            has_usage = True
            cost += float(turn.get("cost") or 0)
            tokens_in += safe_int(turn.get("tokensIn"))
            tokens_out += safe_int(turn.get("tokensOut"))

        project = str(state.get("project", "?"))
        projects[project] = projects.get(project, 0) + 1

        model = str(turn.get("model") or "")
        if model:
            models[model] = models.get(model, 0) + 1

        for name, count in as_dict(turn.get("tools")).items():
            tools[str(name)] = tools.get(str(name), 0) + safe_int(count)

    total = len(turns)
    avg_seconds = seconds / total if total else 0

    lines = [
        f"📊 ▣ OC · last {days} "
        f"{plural_ru(days, 'day', 'days', 'days')}",
        "",
        f"Turns: {total} · sessions: {len(sessions)} "
        f"· projects: {len(projects)}",
        f"Agent runtime: {human_duration(seconds)} "
        f"(average: {human_duration(avg_seconds)} per turn)",
        f"Errors: {errors}",
        "",
        "📦 Changes",
        f"{files} {plural_ru(files, 'file', 'files', 'files')} · +{additions}/-{deletions}",
        "",
        "🧪 Tests",
        f"✅ {passed} · ❌ {failed} · ❔ {unknown}",
    ]

    if has_usage:
        lines.extend(
            [
                "",
                "💰 Spending",
                f"{format_cost(cost)} · "
                f"{format_tokens(tokens_in)} in / "
                f"{format_tokens(tokens_out)} out",
            ]
        )

    if projects:
        top = sorted(
            projects.items(), key=lambda item: item[1], reverse=True
        )[:5]

        lines.extend(["", "📁 Top projects"])
        lines.extend(
            f"{short_text(name, 28)} · {count}" for name, count in top
        )

    if models:
        top = sorted(
            models.items(), key=lambda item: item[1], reverse=True
        )[:5]

        lines.extend(["", "🤖 Models"])
        lines.extend(
            f"{short_text(name.split('/')[-1], 28)} · {count}"
            for name, count in top
        )

    if tools:
        top = sorted(
            tools.items(), key=lambda item: item[1], reverse=True
        )[:6]

        lines.extend(
            [
                "",
                "🛠 Tools",
                " · ".join(f"{name}×{count}" for name, count in top),
            ]
        )

    lines.extend(["", "Period: /ocstats N · projects: /ocproj"])

    return "\n".join(lines)


def handle_ocmute(raw_args: str) -> str:
    raw = raw_args.strip().lower()
    control = read_control()

    if not raw:
        remaining, disabled = mute_state()

        lines = ["🔕 Watcher notifications", "", mute_summary(), ""]

        if remaining <= 0 and not disabled:
            lines.append("All notification levels are enabled.")

        lines.extend(
            [
                "",
                "/ocmute 60          — mute for 60 minutes",
                "/ocmute off         — re-enable all notifications",
                "/ocmute retry done  — disable selected types",
                "",
                "Types: " + ", ".join(NOTIFY_LEVELS),
            ]
        )

        return "\n".join(lines)

    if raw in {"off", "on", "0"}:
        control.pop("muteUntil", None)
        control.pop("disabledLevels", None)

        error = write_control(control)

        if error:
            return f"❌ Could not write control.json:\n{error}"

        return (
            "🔔 All notifications enabled.\n"
            "The watcher will pick up the change within a couple of seconds."
        )

    if raw.isdigit():
        minutes = int(raw)

        if minutes < 1 or minutes > 24 * 60:
            return "Choose from 1 to 1440 minutes."

        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        control["muteUntil"] = (
            until.isoformat().replace("+00:00", "Z")
        )

        error = write_control(control)

        if error:
            return f"❌ Could not write control.json:\n{error}"

        return (
            f"🔕 Muted for {minutes} "
            f"{plural_ru(minutes, 'minute', 'minutes', 'minutes')}.\n"
            f"Until {until.astimezone().strftime('%H:%M')} · "
            "restore: /ocmute off"
        )

    levels = [item for item in re.split(r"[\s,]+", raw) if item]
    unknown = [item for item in levels if item not in NOTIFY_LEVELS]

    if unknown:
        return (
            "Unknown types: " + ", ".join(unknown) + "\n"
            "Available: " + ", ".join(NOTIFY_LEVELS)
        )

    control["disabledLevels"] = sorted(set(levels))

    error = write_control(control)

    if error:
        return f"❌ Could not write control.json:\n{error}"

    return (
        "🔕 Disabled notifications: "
        + ", ".join(sorted(set(levels)))
        + "\nRestore: /ocmute off"
    )


def handle_occlean(raw_args: str) -> str:
    raw = raw_args.strip()

    if raw and not raw.isdigit():
        return "Usage: /occlean [days] · example: /occlean 3"

    days = int(raw) if raw else 7

    if days < 1 or days > 365:
        return "Choose a period from 1 to 365 days."

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Never touch files newer than a day, even for /occlean 1.
    hard_floor = now - timedelta(hours=24)

    removed_states = 0
    removed_instances = 0
    freed = 0

    for state in load_all_states():
        updated = state["_updated"]

        if updated > cutoff or updated > hard_floor:
            continue

        path = state.get("_file")

        if not path:
            continue

        try:
            size = os.path.getsize(path)
            os.remove(path)
            removed_states += 1
            freed += size
        except Exception:
            continue

    for item in load_json_files(INSTANCE_DIR):
        pid = item.get("pid")
        heartbeat = parse_dt(item.get("heartbeatAt"))

        if pid_alive(pid) and heartbeat:
            age = (now - heartbeat).total_seconds()
            if age <= HEARTBEAT_FRESH_SECONDS:
                continue

        if pid_alive(pid) and pid_is_opencode(pid):
            continue

        path = item.get("_file")

        if not path:
            continue

        try:
            os.remove(path)
            removed_instances += 1
        except Exception:
            continue

    if not removed_states and not removed_instances:
        return (
            "🧹 Nothing to clean: no files older than "
            f"{days} {plural_ru(days, 'day', 'days', 'days')}."
        )

    return "\n".join(
        [
            "🧹 Done",
            "",
            f"Deleted state files: {removed_states} "
            f"({human_bytes(freed)})",
            f"Deleted dead instance files: {removed_instances}",
            "",
            "Sessions newer than 24 hours are kept.",
        ]
    )


def safe_handler(handler):
    def wrapped(raw_args: str = "") -> str:
        try:
            return handler(raw_args)
        except Exception as exc:
            return (
                "❌ opencode-control error:\n"
                f"{type(exc).__name__}: {short_text(exc, 600)}"
            )

    wrapped.__name__ = getattr(handler, "__name__", "handler")
    wrapped.__doc__ = getattr(handler, "__doc__", None)

    return wrapped


COMMANDS: list[dict[str, Any]] = [
    {
        "name": "oc",
        "handler": handle_oc,
        "description": "Live OpenCode windows and session details",
        "args_hint": "[number|session_id|all]",
    },
    {
        "name": "ochelp",
        "handler": handle_ochelp,
        "description": "All OpenCode Control commands",
    },
    {
        "name": "ocsum",
        "handler": handle_ocsum,
        "description": "Short summary of the session's last turn",
        "args_hint": "[number|session_id]",
    },
    {
        "name": "ocdiff",
        "handler": handle_ocdiff,
        "description": "Full list of changed files",
        "args_hint": "[number|session_id]",
    },
    {
        "name": "octests",
        "handler": handle_octests,
        "description": "Test runs with exit codes and durations",
        "args_hint": "[number|session_id]",
    },
    {
        "name": "ocfind",
        "handler": handle_ocfind,
        "description": "Search by title, summary, and changed files",
        "args_hint": "<text>",
    },
    {
        "name": "ocproj",
        "handler": handle_ocproj,
        "description": "Project activity over the last 7 days",
        "args_hint": "[name]",
    },
    {
        "name": "ocstats",
        "handler": handle_ocstats,
        "description": "Turn-log totals: time, diffs, tests, and cost",
        "args_hint": "[days]",
    },
    {
        "name": "ocmute",
        "handler": handle_ocmute,
        "description": "Mute watcher notifications",
        "args_hint": "[minutes|off|types]",
    },
    {
        "name": "occlean",
        "handler": handle_occlean,
        "description": "Delete old watcher state files",
        "args_hint": "[days]",
    },
    {
        "name": "occlosed",
        "handler": handle_occlosed,
        "description": "Recently closed OpenCode sessions",
    },
    {
        "name": "oclast",
        "handler": handle_oclast,
        "description": "Last completed OpenCode session",
    },
    {
        "name": "ocwait",
        "handler": handle_ocwait,
        "description": "OpenCode sessions needing attention",
    },
    {
        "name": "today",
        "handler": handle_today,
        "description": "Today's OpenCode activity",
    },
    {
        "name": "errors",
        "handler": handle_errors,
        "description": "Recent problematic OpenCode sessions",
    },
    {
        "name": "sys",
        "handler": handle_sys,
        "description": "CPU, RAM, disk, and processes",
    },
    {
        "name": "hstatus",
        "handler": handle_hstatus,
        "description": "Hermes gateway + OpenCode watcher status",
    },
    {
        "name": "models",
        "handler": handle_models,
        "description": "OpenCode model usage",
        "args_hint": "[days]",
    },
    {
        "name": "notifytest",
        "handler": handle_notifytest,
        "description": "Test proactive Hermes → Telegram delivery",
    },
]


def register(ctx):
    for command in COMMANDS:
        kwargs: dict[str, Any] = {
            "handler": safe_handler(command["handler"]),
            "description": command["description"],
        }

        if command.get("args_hint"):
            kwargs["args_hint"] = command["args_hint"]

        ctx.register_command(command["name"], **kwargs)
