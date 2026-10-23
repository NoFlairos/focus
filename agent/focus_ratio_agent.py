#!/usr/bin/env python3
"""Local tracker and native-messaging bridge for Focus.

No network access is used. The only monitored window metadata is the app id,
window title, and (when the optional browser bridge is installed) site domain.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import ctypes
import fcntl
import datetime as dt
import functools
import html
import json
import ipaddress
import os
import pathlib
import re
import signal
import socket
import socketserver
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import Any, Callable


APP_NAME = "focus-ratio"
CATEGORIES = {"productive", "neutral", "consumption"}
LIMIT_ACTIONS = {"close", "notify", "keep_open"}
LIMIT_PERIODS = {"hour": 120, "day": 720}  # period -> maximum quota in minutes
SNOOZE_SECONDS = 300
MAX_DAY_START_HOUR = 6  # a "day" may end up to 06:00 so late evenings count as the evening before
SUGGEST_LIMIT_SECONDS = 3 * 3600  # weekly use that makes an unlimited entry worth a limit
LIMIT_PROMPT_SECONDS = 120  # how long Now offers "5 more minutes" after a limit closes something
FOCUS_SESSION_MINUTES = {"25", "50", "90"}
MAX_DAILY_BUDGET_MINUTES = 720
IGNORED_APP_IDS: set[str] = set()
DEFAULT_QUOTA_MINUTES = 10
POLL_SECONDS = 1.0
# Review only asks about apps and sites used for a while, not one-off visits.
REVIEW_MIN_SECONDS = 600
REVIEW_DAYS = 7
STATE_HEARTBEAT_SECONDS = 10
BROWSER_ENTRIES_MAX = 50  # windows and site declarations accepted per browser snapshot
SITE_METADATA_MAX = 2000  # remembered site names and identities, pruned daily to known entries
VISIBLE_ENTRIES_MAX = 60  # distinct apps and sites tracked at the same moment
AUTO_LINKS_MAX = 500  # subdomain links made automatically; manual merges are not counted
DB_COMMIT_SECONDS = 30  # usage seconds are batched; a crash loses at most this much tracking
BROWSER_APP_IDS = {"chromium", "chromium-bin", "google-chrome", "google-chrome-stable", "chrome"}


@functools.lru_cache(maxsize=2)
def desktop_app_names(_refresh_period: int = 0) -> dict[str, str]:
    """Use installed desktop entries to turn window classes into application names."""
    names: dict[str, str] = {}
    roots = [xdg_dir("XDG_DATA_HOME", pathlib.Path.home() / ".local/share")]
    roots.extend(pathlib.Path(path) for path in os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if path)
    for root in roots:
        directory = root / "applications"
        if not directory.is_dir():
            continue
        for file in directory.rglob("*.desktop"):
            entry = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                entry.read(file, encoding="utf-8")
                info = entry["Desktop Entry"]
                if info.get("Type") != "Application" or not info.get("Name"):
                    continue
                for key in (file.stem, info.get("StartupWMClass", "")):
                    if key:
                        names.setdefault(key.casefold(), " ".join(info["Name"].split())[:120])
            except (OSError, UnicodeError, configparser.Error, KeyError):
                continue
    return names


def app_display_name(app_id: str) -> str:
    # Desktop entries can appear or change while this user service stays alive.
    return desktop_app_names(int(time.monotonic() // 300)).get(app_id.casefold(), app_id)


def target_display_name(target_id: str, saved_name: str = "") -> str:
    # The snapshot names every entry each second; desktop names refresh every 5 minutes.
    return cached_display_name(target_id, saved_name, int(time.monotonic() // 300))


@functools.lru_cache(maxsize=4096)
def cached_display_name(target_id: str, saved_name: str, desktop_period: int) -> str:
    raw_id = target_id.split(":", 1)[-1]
    if saved_name and saved_name.casefold() != raw_id.casefold():
        return saved_name
    is_site = target_id.startswith("site:")
    if target_id.startswith("app:"):
        desktop_name = app_display_name(raw_id)
        if desktop_name != raw_id:
            return desktop_name
        match = re.match(r"^chrome-(.+?)(?:__.*)?$", raw_id, re.IGNORECASE)
        if match:
            raw_id = match.group(1)
            is_site = True
    domain = raw_id.lower().removeprefix("www.")
    if is_site and "." in domain:
        return domain
    parts = [part for part in re.split(r"[._-]+", raw_id) if part and part.lower() not in
             {"org", "com", "io", "net", "app", "desktop"}]
    return " ".join(part.capitalize() for part in parts) or raw_id


def xdg_dir(name: str, default: str | pathlib.Path) -> pathlib.Path:
    """XDG base directory. Empty or relative values are ignored, as the specification requires."""
    value = os.environ.get(name, "")
    return pathlib.Path(value) if os.path.isabs(value) else pathlib.Path(default)


def config_home() -> pathlib.Path:
    return xdg_dir("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")


def state_home() -> pathlib.Path:
    return xdg_dir("XDG_STATE_HOME", pathlib.Path.home() / ".local/state")


def runtime_home() -> pathlib.Path:
    return xdg_dir("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")


CONFIG_DIR = config_home() / APP_NAME
STATE_DIR = state_home() / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
# Rewritten every second for the bar widget: keep it in RAM (tmpfs), not on the SSD.
STATE_PATH = runtime_home() / APP_NAME / "state.json"
DB_PATH = STATE_DIR / "history.sqlite3"
SOCKET_PATH = STATE_DIR / "control.sock"


def default_config() -> dict[str, Any]:
    return {
        "version": 1,
        "schedule": {"weekdays": [0, 1, 2, 3, 4], "start": "08:00", "end": "17:00"},
        "default_quota_minutes": DEFAULT_QUOTA_MINUTES,
        "targets": {},
        "review_targets": [],
        "ignored_targets": [],
        "service_links": {},
        "site_names": {},
        "site_identity": {},
        "auto_links": [],  # subdomain links Focus made itself, oldest first; see remember_auto_link
        "subdomain_rules": {},
        "subdomain_destinations": {},
        "subdomain_rule_schema": 2,
        "link_schema": 2,
        "independent_targets": [],
        "warn_before_limit": True,
        "weekly_summary": True,
        "last_weekly_summary": "",
        "daily_budget_minutes": 0,
        "day_start_hour": 4,
        "dismissed_limit_suggestions": {},
        "snoozes": {},
        "focus_session": {"until": None},
        "dismissed_suggestions": [],
        "pause_state": {"active": False, "until": None},
    }


def ensure_dirs() -> None:
    """Settings and history are private: owner-only folders, and owner-only files from older installs."""
    for directory in (CONFIG_DIR, STATE_DIR):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
    for path in (CONFIG_PATH, DB_PATH, *(DB_PATH.with_name(DB_PATH.name + suffix) for suffix in ("-wal", "-shm", "-journal"))):
        try:
            os.chmod(path, 0o600)
        except FileNotFoundError:
            pass


def create_private(path: pathlib.Path):
    """Open a new owner-only file; the mode is set at creation, never after the data is written."""
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600),
                     "w", encoding="utf-8", newline="")


def sanitize_config(value: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Replace hand-edited or corrupted settings with defaults, key by key, so a bad value
    can never stop the service in a restart loop."""
    for key, default in defaults.items():
        if type(value[key]) is not type(default):
            value[key] = default
    try:
        value["schedule"] = valid_schedule(value["schedule"])
    except ValueError:
        value["schedule"] = defaults["schedule"]
    for key, low, high in (("day_start_hour", 0, MAX_DAY_START_HOUR),
                           ("daily_budget_minutes", 0, MAX_DAILY_BUDGET_MINUTES),
                           ("default_quota_minutes", 1, max(LIMIT_PERIODS.values()))):
        if not low <= value[key] <= high:
            value[key] = defaults[key]
    value["targets"] = {key: target for key, target in value["targets"].items()
                        if isinstance(key, str) and isinstance(target, dict)}
    for key in ("service_links", "site_names", "subdomain_rules", "subdomain_destinations"):
        value[key] = {name: item for name, item in value[key].items() if isinstance(item, str)}
    value["site_identity"] = {name: item for name, item in value["site_identity"].items() if isinstance(item, dict)}
    for key in ("review_targets", "ignored_targets", "independent_targets", "dismissed_suggestions", "auto_links"):
        value[key] = [item for item in value[key] if isinstance(item, str)]
    return value


def load_config() -> dict[str, Any]:
    ensure_dirs()
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported config")
        defaults = default_config()
        # Missing schemas must still trigger migrations for older settings.
        defaults.pop("link_schema")
        defaults["subdomain_rule_schema"] = 1
        for key, default in defaults.items():
            value.setdefault(key, default)
        for retired in ("hide_excluded", "hidden_excluded_targets"):
            value.pop(retired, None)
        return sanitize_config(value, defaults)
    except FileNotFoundError:
        value = default_config()
        save_config(value)
        return value
    except (json.JSONDecodeError, ValueError):
        broken = CONFIG_PATH.with_suffix(".json.broken")
        CONFIG_PATH.replace(broken)
        value = default_config()
        save_config(value)
        return value


def atomic_json(path: pathlib.Path, value: Any, indent: int | None = 2) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.unlink()  # a leftover from an interrupted write may predate private modes
    except FileNotFoundError:
        pass
    with create_private(temp) as output:
        output.write(json.dumps(value, ensure_ascii=False, indent=indent) + "\n")
    temp.replace(path)


def save_config(value: dict[str, Any]) -> None:
    atomic_json(CONFIG_PATH, value)


def hypr_socket() -> pathlib.Path | None:
    runtime_dir = runtime_home() / "hypr"
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if signature and (runtime_dir / signature / ".socket.sock").exists():
        return runtime_dir / signature / ".socket.sock"
    sockets = list(runtime_dir.glob("*/.socket.sock"))
    return max(sockets, key=lambda path: path.stat().st_mtime) if sockets else None


# Talk to Hyprland's IPC socket directly: spawning hyprctl several times per
# second kept the CPU awake. A tick asks for the same data more than once, so
# answers are reused for a few milliseconds.
_hypr_cache: dict[str, tuple[float, Any]] = {}


def hypr_query(command: str) -> Any:
    cached = _hypr_cache.get(command)
    if cached and time.monotonic() - cached[0] < 0.05:
        return cached[1]
    parsed: Any = None
    path = hypr_socket()
    if path:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.5)
                client.connect(str(path))
                client.sendall(b"j/" + command.encode())
                chunks = []
                while chunk := client.recv(65536):
                    chunks.append(chunk)
            parsed = json.loads(b"".join(chunks))
        except (OSError, json.JSONDecodeError, ValueError):
            parsed = None
    if parsed is None:
        try:
            result = subprocess.run(["hyprctl", "-j", command], capture_output=True, text=True, timeout=1.5, check=True)
            parsed = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return None
    _hypr_cache[command] = (time.monotonic(), parsed)
    return parsed


def hypr_json(command: str) -> list[dict[str, Any]]:
    parsed = hypr_query(command)
    return parsed if isinstance(parsed, list) else []


def focused_window_address() -> str:
    parsed = hypr_query("activewindow")
    return str(parsed.get("address") or "") if isinstance(parsed, dict) else ""


def browser_is_running() -> bool:
    # Include windows on other workspaces, even while tracking is paused.
    return any(str(client.get("class") or client.get("initialClass") or "").casefold() in BROWSER_APP_IDS
               and client.get("mapped") is not False for client in hypr_json("clients"))


def visible_clients() -> list[dict[str, Any]]:
    """Windows on any currently displayed workspace, independent of focus.

    Hyprland does not expose reliable pixel-level occlusion for every client.
    For this first version, visible means mapped, not hidden/minimized, and on a
    workspace currently displayed on a monitor.
    """
    active_workspaces = {
        int(m.get("activeWorkspace", {}).get("id", -999))
        for m in hypr_json("monitors")
        if isinstance(m.get("activeWorkspace"), dict)
    }
    if not active_workspaces:
        return []

    found: list[dict[str, Any]] = []
    for client in hypr_json("clients"):
        workspace = client.get("workspace") or {}
        size = client.get("size") or [0, 0]
        if not isinstance(workspace, dict):
            continue
        try:
            workspace_id = int(workspace.get("id", -999))
        except (TypeError, ValueError):
            continue
        if workspace_id not in active_workspaces:
            continue
        if client.get("mapped") is False or client.get("hidden") is True:
            continue
        if len(size) < 2 or int(size[0]) <= 0 or int(size[1]) <= 0:
            continue
        app_id = str(client.get("class") or client.get("initialClass") or "").strip()[:120]
        address = str(client.get("address") or "")
        if not app_id or not address or app_id.casefold() in IGNORED_APP_IDS:
            continue
        found.append({
            "app_id": app_id,
            "window_title": str(client.get("title") or ""),
            "address": address,
        })
    return found


def in_work_hours(now: dt.datetime, schedule: dict[str, Any]) -> bool:
    weekdays = {int(day) for day in schedule.get("weekdays", [0, 1, 2, 3, 4])}
    start = dt.time.fromisoformat(schedule.get("start", "08:00"))
    end = dt.time.fromisoformat(schedule.get("end", "17:00"))
    current = now.time().replace(tzinfo=None)
    if start == end:
        return now.weekday() in weekdays
    if start < end:
        return now.weekday() in weekdays and start <= current < end
    return (now.weekday() in weekdays and current >= start) or (
        (now.weekday() - 1) % 7 in weekdays and current < end)


def valid_schedule(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("weekdays"), list):
        raise ValueError("invalid schedule")
    weekdays = value["weekdays"]
    if any(type(day) is not int or day < 0 or day > 6 for day in weekdays):
        raise ValueError("weekdays must be 0–6")
    times = {}
    for key in ("start", "end"):
        text = value.get(key)
        if not isinstance(text, str):
            raise ValueError("time must be HH:MM")
        try:
            parsed = dt.time.fromisoformat(text)
        except ValueError as error:
            raise ValueError("time must be HH:MM") from error
        if parsed.isoformat(timespec="minutes") != text:
            raise ValueError("time must be HH:MM")
        times[key] = text
    return {"weekdays": sorted(set(weekdays)), **times}


def current_hour_bucket(now: dt.datetime) -> str:
    return now.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


@functools.lru_cache(maxsize=4096)
def clean_site_name(name: str) -> str:
    """Drop parenthesised asides such as "X (formerly Twitter)" or "(3) Inbox"."""
    cleaned = " ".join(re.sub(r"\([^()]*\)", " ", name).split()).strip(" -–—|·:")
    return cleaned or " ".join(name.split())


def format_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def browser_domain(value: Any) -> str:
    """A hostname reported by the browser, or "" when it is not a plausible one."""
    domain = canonical_domain(str(value or ""))
    return domain if len(domain) <= 253 and re.fullmatch(r"[a-z0-9.\-\[\]:]+", domain) else ""


def canonical_domain(domain: str) -> str:
    value = domain.lower().strip().rstrip(".")
    for prefix in ("www.", "m."):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def web_app_domain(app_id: str) -> str:
    """Extract a domain from Chromium's standalone web-app window class."""
    match = re.fullmatch(r"chrome-([a-z0-9.-]+\.[a-z]{2,})(?:__.*)?", app_id.casefold())
    return canonical_domain(match.group(1)) if match else ""


@functools.lru_cache(maxsize=2)
def desktop_app_domains(_refresh_period: int = 0) -> dict[str, str]:
    """Find explicit web-app URLs in desktop launchers, keyed by window class."""
    domains: dict[str, str] = {}
    roots = [xdg_dir("XDG_DATA_HOME", pathlib.Path.home() / ".local/share")]
    roots.extend(pathlib.Path(path) for path in os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if path)
    for root in roots:
        directory = root / "applications"
        if not directory.is_dir():
            continue
        for file in directory.rglob("*.desktop"):
            entry = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                entry.read(file, encoding="utf-8")
                info = entry["Desktop Entry"]
                if info.get("Type") != "Application":
                    continue
                command = info.get("Exec", "")
                match = re.search(r"(?:--app(?:-url)?|--url)=['\"]?(https?://[^\s'\"]+)", command)
                if not match:
                    continue
                domain = canonical_domain(urllib.parse.urlparse(match.group(1)).hostname or "")
                if domain:
                    for key in (file.stem, info.get("StartupWMClass", "")):
                        if key:
                            domains.setdefault(key.casefold(), domain)
            except (OSError, UnicodeError, configparser.Error, KeyError, ValueError):
                continue
    return domains


def service_site_for_app(app_id: str) -> str:
    """Resolve a window class to one unambiguous site target, if possible."""
    app_id = app_id.casefold()
    if app_id in BROWSER_APP_IDS:
        return ""
    domain = web_app_domain(app_id) or desktop_app_domains(int(time.monotonic() // 300)).get(app_id, "")
    if domain:
        return "site:" + domain
    return ""


SESSION_STATUS_SECONDS = 5  # lock/idle changes slowly; polling loginctl every tick cost a process per second
_session_cache: tuple[float, tuple[bool, bool]] | None = None


def session_status() -> tuple[bool, bool]:
    global _session_cache
    session_id = os.environ.get("XDG_SESSION_ID")
    if not session_id:
        return False, False
    if _session_cache and time.monotonic() - _session_cache[0] < SESSION_STATUS_SECONDS:
        return _session_cache[1]
    try:
        result = subprocess.run(
            ["loginctl", "show-session", session_id, "--property=LockedHint", "--property=IdleHint"],
            capture_output=True, text=True, timeout=0.8, check=True,
        )
        flags = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        status = flags.get("LockedHint", "").lower() == "yes", flags.get("IdleHint", "").lower() == "yes"
    except (OSError, subprocess.SubprocessError):
        status = False, False
    _session_cache = (time.monotonic(), status)
    return status


class Store:
    def __init__(self) -> None:
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS hourly_usage (
              target_id TEXT NOT NULL, bucket TEXT NOT NULL, seconds REAL NOT NULL,
              PRIMARY KEY (target_id, bucket)
            );
            CREATE TABLE IF NOT EXISTS daily_usage (
              day TEXT NOT NULL, target_id TEXT NOT NULL, category TEXT NOT NULL,
              seconds REAL NOT NULL, PRIMARY KEY (day, target_id, category)
            );
            CREATE INDEX IF NOT EXISTS daily_usage_category_day ON daily_usage(category, day);
            CREATE TABLE IF NOT EXISTS daily_screen_time (
              day TEXT PRIMARY KEY, seconds REAL NOT NULL, started_at TEXT NOT NULL
            );
        """)
        self.db.commit()
        self.last_pruned_day: dt.date | None = None
        self.last_commit = time.monotonic()

    def prune(self, now: dt.datetime) -> None:
        if self.last_pruned_day == now.date():
            return
        with self.db:
            self.db.execute("DELETE FROM daily_usage WHERE day < ?", ((now.date() - dt.timedelta(days=45)).isoformat(),))
            self.db.execute("DELETE FROM daily_screen_time WHERE day < ?", ((now.date() - dt.timedelta(days=45)).isoformat(),))
            for app_id in IGNORED_APP_IDS:
                self.db.execute("DELETE FROM daily_usage WHERE target_id=? AND category='unclassified'", ("app:" + app_id,))
            self.db.execute("DELETE FROM hourly_usage WHERE bucket < ?", ((now - dt.timedelta(days=3)).isoformat(timespec="seconds"),))
        self.last_pruned_day = now.date()

    def used_this_hour(self, target_id: str, bucket: str) -> float:
        row = self.db.execute("SELECT seconds FROM hourly_usage WHERE target_id=? AND bucket=?", (target_id, bucket)).fetchone()
        return float(row[0]) if row else 0.0

    def target_ids(self) -> set[str]:
        rows = self.db.execute("SELECT target_id FROM daily_usage UNION SELECT target_id FROM hourly_usage")
        return {str(row[0]) for row in rows}

    def merge_target(self, source: str, destination: str) -> None:
        if source == destination:
            return
        with self.db:
            for day, category, seconds in self.db.execute(
                    "SELECT day, category, seconds FROM daily_usage WHERE target_id=?", (source,)).fetchall():
                self.db.execute("""INSERT INTO daily_usage(day,target_id,category,seconds) VALUES(?,?,?,?)
                    ON CONFLICT(day,target_id,category) DO UPDATE SET seconds=seconds+excluded.seconds""",
                    (day, destination, category, seconds))
            self.db.execute("DELETE FROM daily_usage WHERE target_id=?", (source,))
            for bucket, seconds in self.db.execute(
                    "SELECT bucket, seconds FROM hourly_usage WHERE target_id=?", (source,)).fetchall():
                self.db.execute("""INSERT INTO hourly_usage(target_id,bucket,seconds) VALUES(?,?,?)
                    ON CONFLICT(target_id,bucket) DO UPDATE SET seconds=seconds+excluded.seconds""",
                    (destination, bucket, seconds))
            self.db.execute("DELETE FROM hourly_usage WHERE target_id=?", (source,))

    def add_times(self, categories: dict[str, str], seconds: float, bucket: str, day: str) -> None:
        # Record availability even on inactive days; older history stays unknown.
        # One elapsed interval per tick, regardless of target/window count.
        # Writes stay in the open transaction (visible to this connection's reads);
        # flush() commits them in batches instead of hitting the SSD every second.
        self.db.execute("""
            INSERT INTO daily_screen_time(day,seconds,started_at) VALUES(?,?,?)
            ON CONFLICT(day) DO UPDATE SET seconds=seconds+excluded.seconds
        """, (day, max(0.0, seconds) if categories else 0.0,
              dt.datetime.now().astimezone().isoformat(timespec="seconds")))
        if seconds > 0 and categories:
            for target_id, category in categories.items():
                self.db.execute("""
                    INSERT INTO daily_usage(day,target_id,category,seconds) VALUES(?,?,?,?)
                    ON CONFLICT(day,target_id,category) DO UPDATE SET seconds=seconds+excluded.seconds
                """, (day, target_id, category, seconds))
                if category == "consumption":
                    self.db.execute("""
                        INSERT INTO hourly_usage(target_id,bucket,seconds) VALUES(?,?,?)
                        ON CONFLICT(target_id,bucket) DO UPDATE SET seconds=seconds+excluded.seconds
                    """, (target_id, bucket, seconds))
        self.flush()

    def flush(self, force: bool = False) -> None:
        if force or time.monotonic() - self.last_commit >= DB_COMMIT_SECONDS:
            self.db.commit()
            self.last_commit = time.monotonic()

    def close(self) -> None:
        """Commit batched usage, then close: a clean stop loses nothing."""
        self.flush(force=True)
        self.db.close()

    def history(self, days: int = 30) -> list[dict[str, Any]]:
        start = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
        rows = self.db.execute("""
            SELECT day, category, SUM(seconds) FROM daily_usage WHERE day>=?
            GROUP BY day, category ORDER BY day
        """, (start,)).fetchall()
        days_map: dict[str, dict[str, Any]] = {}
        for day, category, seconds in rows:
            days_map.setdefault(day, {})[category] = round(float(seconds) / 60.0, 1)
        for day, seconds, started_at in self.db.execute(
                "SELECT day, seconds, started_at FROM daily_screen_time WHERE day>=?", (start,)):
            days_map.setdefault(day, {})["screen_seconds"] = int(seconds)
            days_map[day]["screen_started_at"] = started_at
        return [{"day": day, **values} for day, values in sorted(days_map.items())]

    def consumption_today(self, day: str, target_id: str | None = None) -> float:
        query = "SELECT SUM(seconds) FROM daily_usage WHERE day=? AND category='consumption'"
        args: tuple = (day,)
        if target_id is not None:
            query += " AND target_id=?"
            args += (target_id,)
        row = self.db.execute(query, args).fetchone()
        return float(row[0] or 0)

    def usage_by_target(self, start: str, end: str) -> dict[str, dict[str, float]]:
        """Seconds per target and category between two days, inclusive."""
        result: dict[str, dict[str, float]] = {}
        for target_id, category, seconds in self.db.execute("""SELECT target_id, category, SUM(seconds) FROM daily_usage
                WHERE day>=? AND day<=? GROUP BY target_id, category""", (start, end)):
            result.setdefault(str(target_id), {})[str(category)] = float(seconds)
        return result

    def day_breakdown(self, start: str, top: int = 8) -> dict[str, list[tuple[str, str, float]]]:
        """Largest entries per day since `start`: (target, main category, seconds)."""
        days: dict[str, dict[str, dict[str, float]]] = {}
        for day, target_id, category, seconds in self.db.execute("""SELECT day, target_id, category, SUM(seconds)
                FROM daily_usage WHERE day>=? GROUP BY day, target_id, category""", (start,)):
            days.setdefault(day, {}).setdefault(target_id, {})[category] = float(seconds)
        return {day: sorted(((target, max(cats, key=cats.get), sum(cats.values())) for target, cats in targets.items()),
                            key=lambda item: -item[2])[:top]
                for day, targets in days.items()}

    def target_today(self, day: str) -> dict[str, float]:
        rows = self.db.execute("SELECT target_id, SUM(seconds) FROM daily_usage WHERE day=? GROUP BY target_id", (day,)).fetchall()
        return {target_id: float(seconds) for target_id, seconds in rows}

    def pending_targets(self, days: int = 30) -> dict[str, float]:
        """Unclassified seconds per target over the last `days` days."""
        start = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
        rows = self.db.execute("""SELECT target_id, SUM(seconds) FROM daily_usage
            WHERE category='unclassified' AND day>=? GROUP BY target_id""", (start,)).fetchall()
        return {str(target_id): float(seconds) for target_id, seconds in rows}

    def forget_unclassified(self, target_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM daily_usage WHERE target_id=? AND category='unclassified'", (target_id,))

    def classify_pending(self, target_id: str, category: str) -> None:
        with self.db:
            pending = self.db.execute("SELECT day, seconds FROM daily_usage WHERE target_id=? AND category='unclassified'", (target_id,)).fetchall()
            for day, seconds in pending:
                self.db.execute("""INSERT INTO daily_usage(day,target_id,category,seconds) VALUES(?,?,?,?)
                    ON CONFLICT(day,target_id,category) DO UPDATE SET seconds=seconds+excluded.seconds""",
                    (day, target_id, category, float(seconds)))
            self.db.execute("DELETE FROM daily_usage WHERE target_id=? AND category='unclassified'", (target_id,))


@functools.lru_cache(maxsize=1)
def public_suffix_context():
    """Use the system's maintained suffix data without fetching anything."""
    library = ctypes.CDLL("libpsl.so.5")
    library.psl_builtin.restype = ctypes.c_void_p
    library.psl_is_public_suffix2.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    library.psl_is_public_suffix2.restype = ctypes.c_int
    return library, library.psl_builtin()


@functools.lru_cache(maxsize=4096)
def registrable_domain(domain: str, suffix_type: int = 1) -> str:
    """Return the registrable domain; type 1 uses ICANN suffixes, 3 adds hosting suffixes."""
    domain = canonical_domain(domain)
    if not domain:
        return ""
    try:
        ipaddress.ip_address(domain)
        return domain
    except ValueError:
        pass
    library, context = public_suffix_context()
    labels = domain.split(".")
    for index in range(len(labels)):
        if library.psl_is_public_suffix2(context, ".".join(labels[index:]).encode("utf-8"), suffix_type):
            return ".".join(labels[index - 1:]) if index else ""
    return domain


def domain_family(domain: str) -> str:
    """ICANN family: what an explicit Group rule covers, including hosted sibling projects."""
    return registrable_domain(domain, 1)


def site_root(domain: str) -> str:
    """One site, honouring hosting boundaries (each *.pages.dev project is its own site)."""
    return registrable_domain(domain, 3)


class Notifier:
    """Desktop notifications over D-Bus. Unlike notify-send, nothing shown in a notification
    ever appears in a process command line, which other users may read from /proc."""

    SERVICE = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"
    ACTION_SECONDS = 3600  # a click on an older limit notification no longer counts

    def __init__(self, on_default: Callable[[str], None]) -> None:
        self.on_default = on_default
        self.waiting: dict[int, tuple[str, float]] = {}  # notification id -> (snooze target, sent at)
        self.lock = threading.Lock()
        self.bus = None
        ready = threading.Event()
        threading.Thread(target=self.listen, args=(ready,), daemon=True).start()
        ready.wait(5)

    def listen(self, ready: threading.Event) -> None:
        # Signals are delivered to the context that subscribed, so this thread owns one.
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
            context = GLib.MainContext.new()
            context.push_thread_default()
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(self.SERVICE, self.SERVICE, "ActionInvoked", self.PATH, None,
                                      Gio.DBusSignalFlags.NONE, self.on_action)
        except Exception:
            self.bus = None
            return
        finally:
            ready.set()
        GLib.MainLoop(context).run()

    def on_action(self, connection, sender, path, interface, signal_name, parameters) -> None:
        notification_id, action = parameters.unpack()
        with self.lock:
            target, sent_at = self.waiting.pop(notification_id, ("", 0.0))
        if action == "default" and target and time.monotonic() - sent_at < self.ACTION_SECONDS:
            self.on_default(target)

    def send(self, title: str, body: str, snooze_target: str = "") -> None:
        if self.bus is None:
            return
        from gi.repository import Gio, GLib
        # Omarchy shows no action buttons; clicking a notification runs its "default"
        # action. Critical is the only urgency it keeps on screen until the user acts.
        actions = ["default", "5 more minutes"] if snooze_target else []
        hints = {"urgency": GLib.Variant("y", 2)} if snooze_target else {}
        try:
            reply = self.bus.call_sync(
                self.SERVICE, self.PATH, self.SERVICE, "Notify",
                GLib.Variant("(susssasa{sv}i)", ("Focus", 0, "preferences-system-time", title, body, actions, hints, -1)),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 2000, None)
        except Exception:
            return
        if snooze_target:
            now = time.monotonic()
            with self.lock:
                # Closed notifications send no action; their entries simply age out.
                self.waiting = {key: entry for key, entry in self.waiting.items() if now - entry[1] < self.ACTION_SECONDS}
                self.waiting[reply.unpack()[0]] = (snooze_target, now)


class Runtime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.last_tick_error, self.last_tick_error_at = "", 0.0
        self.tracking = False  # set by each tick: in schedule, unlocked, not idle or paused
        self.notifier: Notifier | None = None  # connects to the session bus on first use
        self.config = load_config()
        self.store = Store()
        # Pre-manual-group versions could fold a web app into its parent
        # domain (e.g. a service subdomain into a search site). Correct only
        # those legacy links; historical totals cannot be reconstructed.
        if self.config.get("link_schema", 1) < 2:
            for source, destination in list(self.config["service_links"].items()):
                if not source.startswith("app:") or not destination.startswith("site:"):
                    continue
                exact = service_site_for_app(source[4:])
                if exact and exact != destination and exact[5:].endswith("." + destination[5:]):
                    self.config["service_links"][source] = exact
            self.config["link_schema"] = 2
            save_config(self.config)
        self.reconciled: int | None = None
        self.browser_windows: dict[str, dict[str, Any]] = {}
        self.migrate_subdomain_rules()
        self.reconcile_targets()
        self.browser_sessions: dict[str, tuple[float, list]] = {}
        self.last_browser_snapshot = 0.0
        self.browser_opened_at: float | None = None
        self.paused = bool(self.config["pause_state"].get("active"))
        self.pause_until = self.config["pause_state"].get("until")
        self.warned_limits: set[tuple[str, str]] = set()
        self.last_data_action: dict[str, Any] = {}
        self.notified_limits: set[tuple[str, str]] = set()
        self.limit_prompts: dict[str, float] = {}
        self.latest_state: dict[str, Any] = {"tracked": [], "today": {}, "history": []}
        self.written_state = ""
        self.written_at = 0.0

    def resume_if_due(self, now: dt.datetime) -> None:
        if self.paused and self.pause_until and now.timestamp() >= self.pause_until:
            self.paused = False
            self.pause_until = None
            self.config["pause_state"] = {"active": False, "until": None}
            save_config(self.config)

    def tracking_date(self, now: dt.datetime) -> dt.date:
        """Calendar date of the tracking day; hours before day_start_hour belong to the previous day."""
        return (now - dt.timedelta(hours=int(self.config["day_start_hour"]))).date()

    def limit_suggestions(self, today: dt.date) -> list[dict[str, Any]]:
        """Heavily used entries without an enforced limit, with a daily limit to propose."""
        start = (today - dt.timedelta(days=6)).isoformat()
        week = "%d-W%02d" % today.isocalendar()[:2]
        usage = self.store.usage_by_target(start, today.isoformat())
        suggestions = []
        for target_id, target in self.config["targets"].items():
            category, action = target.get("category"), target.get("limit_action", "close")
            unlimited = category == "neutral" or (category == "consumption" and action == "keep_open")
            total = sum(usage.get(target_id, {}).values())
            # The browser itself only hosts sites; its sites get their own suggestions.
            if (not unlimited or total < SUGGEST_LIMIT_SECONDS or target_id in self.config["ignored_targets"]
                    or target_id[4:] in BROWSER_APP_IDS
                    or self.config["dismissed_limit_suggestions"].get(target_id) == week):
                continue
            # A quarter below the current daily average, in 15-minute steps.
            minutes = max(15, min(MAX_DAILY_BUDGET_MINUTES, int(total / 7 / 60 * 0.75) // 15 * 15))
            suggestions.append({"id": target_id, "name": target_display_name(target_id, target.get("name", "")),
                                "week_seconds": int(total), "daily_minutes": minutes})
        return sorted(suggestions, key=lambda item: -item["week_seconds"])[:3]

    def focus_until(self, now: dt.datetime) -> float | None:
        until = self.config["focus_session"].get("until")
        return until if until and now.timestamp() < until else None

    def limit_status(self, target_id: str, target: dict[str, Any], now: dt.datetime) -> dict[str, Any] | None:
        """One place for every reason a Consumption entry runs out: its own limit
        (per hour or per day), the daily budget, or a focus session."""
        if target.get("category") != "consumption":
            return None
        period = target.get("limit_period", "hour")
        period = period if period in LIMIT_PERIODS else "hour"
        day = self.tracking_date(now).isoformat()
        key = current_hour_bucket(now) if period == "hour" else "day:" + day
        quota = int(target.get("quota_minutes", self.config["default_quota_minutes"])) * 60
        used = (self.store.used_this_hour(target_id, key) if period == "hour"
                else self.store.consumption_today(day, target_id))
        snoozed = self.config["snoozes"].get(target_id) == key
        extra = SNOOZE_SECONDS if snoozed else 0
        remaining, reason = max(0, quota + extra - int(used)), "limit"
        budget = int(self.config["daily_budget_minutes"]) * 60
        if budget:
            left = max(0, budget + extra - int(self.store.consumption_today(day)))
            if left < remaining:
                remaining, reason = left, "budget"
        if self.focus_until(now):
            remaining, reason = 0, "focus"
        return {"quota": quota, "used": int(used), "remaining": remaining, "period": period,
                "period_key": key, "reason": reason, "snoozed": snoozed,
                "can_snooze": reason != "focus" and not snoozed}

    def notify(self, title: str, body: str, snooze_target: str = "") -> None:
        """Desktop notification; a limit notification offers one 5-minute extension."""
        if snooze_target:
            body += " Click for 5 more minutes."
        if self.notifier is None:
            self.notifier = Notifier(lambda target: self.handle_message({"op": "snooze", "target_id": target}))
        # Bodies may be rendered as markup; names come from apps and sites.
        self.notifier.send(title, html.escape(body, quote=False), snooze_target)

    def weekly_report(self, now: dt.datetime) -> None:
        """Once per ISO week, summarise the previous week if it has recorded screen time."""
        today = self.tracking_date(now)
        week = "%d-W%02d" % today.isocalendar()[:2]
        if not self.config["weekly_summary"] or self.config["last_weekly_summary"] == week:
            return
        self.config["last_weekly_summary"] = week
        save_config(self.config)
        monday = today - dt.timedelta(days=today.weekday())
        history = {row["day"]: row for row in self.store.history(21)}

        def totals(start: dt.date) -> tuple[int, int, float]:
            rows = [history[day] for day in ((start + dt.timedelta(days=i)).isoformat() for i in range(7)) if day in history]
            recorded = [row for row in rows if "screen_seconds" in row]
            return (sum(row["screen_seconds"] for row in recorded), len(recorded),
                    sum(row.get("consumption", 0) for row in rows))

        last, last_days, consumed = totals(monday - dt.timedelta(days=7))
        before, before_days, _ = totals(monday - dt.timedelta(days=14))
        if not last_days:
            return
        body = format_duration(last) + " screen time · " + format_duration(consumed * 60) + " consumption"
        if before_days:
            body += " · " + ("+" if last >= before else "−") + format_duration(abs(last - before)) + " vs week before"
        self.notify("Last week in Focus", body)

    @staticmethod
    def weekly_summary(history: list[dict], today: dt.date) -> dict:
        def period(offset: int) -> dict:
            end = today - dt.timedelta(days=offset)
            start = end - dt.timedelta(days=6)
            rows = [row for row in history if start.isoformat() <= row["day"] <= end.isoformat()]
            recorded = [row for row in rows if "screen_seconds" in row]
            return {"screen_seconds": sum(row["screen_seconds"] for row in recorded),
                    "recorded_days": len(recorded),
                    **{category: round(sum(row.get(category, 0) for row in rows), 1)
                       for category in ("productive", "neutral", "consumption")}}
        current, previous = period(0), period(7)
        return {"current": current, "previous": previous,
                "screen_delta": current["screen_seconds"] - previous["screen_seconds"]
                if current["recorded_days"] and previous["recorded_days"] else None}

    def group_suggestions(self, rows: list[dict]) -> list[dict]:
        """Same-name entries across domains (e.g. an app and its site); subdomains group automatically."""
        candidates = [row for row in rows if row["configured"]]
        # Normalize once: this runs every tick and the pairwise regex dominated its cost.
        names = [re.sub(r"[^\w]", "", row["name"].casefold()) for row in candidates]
        suggestions = []
        for index, source in enumerate(candidates):
            name = names[index]
            if len(name) < 3:
                continue
            for offset, destination in enumerate(candidates[index + 1:], index + 1):
                if names[offset] != name:
                    continue
                key = "|".join(sorted((source["id"], destination["id"])))
                if key not in self.config["dismissed_suggestions"]:
                    suggestions.append({"source": source["id"], "destination": destination["id"],
                                        "name": source["name"], "reason": "Matching names"})
        return suggestions[:8]

    def resolve_target_id(self, target_id: str) -> str:
        visited = set()
        while target_id in self.config["service_links"] and target_id not in visited:
            visited.add(target_id)
            target_id = self.config["service_links"][target_id]
        if target_id.startswith("app:") and not visited and target_id not in self.config["independent_targets"]:
            inferred = service_site_for_app(target_id[4:])
            if inferred and inferred != target_id:
                return self.resolve_target_id(inferred)
        return target_id

    def migrate_subdomain_rules(self) -> None:
        if self.config["subdomain_rule_schema"] >= 2:
            return
        rules, destinations = {}, {}
        for domain, mode in self.config["subdomain_rules"].items():
            family = domain_family(domain)
            if not family:
                continue
            rules[family] = mode
            target = self.resolve_target_id("site:" + domain)
            if target in self.config["targets"]:
                destinations[family] = target
        self.config["subdomain_rules"] = rules
        self.config["subdomain_destinations"] = destinations
        self.config["subdomain_rule_schema"] = 2
        save_config(self.config)

    def site_identity_matches(self, first: str, second: str) -> bool:
        first = self.config["site_identity"].get(first, {})
        second = self.config["site_identity"].get(second, {})
        application = first.get("application_name", "").casefold()
        other_application = second.get("application_name", "").casefold()
        if application and other_application and application != other_application:
            return False
        return bool((application and application == other_application)
                    or (first.get("manifest") and first.get("manifest") == second.get("manifest")))

    def distinct_service(self, domain: str, anchor: str) -> bool:
        """Evidence that a subdomain is its own service: own web app or declared name."""
        identities = self.config["site_identity"]
        first, second = identities.get(domain, {}), identities.get(anchor)
        application = first.get("application_name", "").casefold()
        if second is None:
            return bool(first.get("manifest") or application)
        # A name only the subdomain declares marks its own app; a parent-only name does not.
        return ((bool(application) and application != second.get("application_name", "").casefold())
                or first.get("manifest", "") != second.get("manifest", ""))

    def link_sites(self, domains: set[str]) -> None:
        """Fold subdomains into their site unless they show signs of a distinct service.

        Smart: same site merges by default; sibling projects on a hosting
        domain need a shared identity. Group: the whole family merges.
        """
        targets = self.config["targets"]
        known = set(targets) | self.store.target_ids() | set(self.config["review_targets"])
        ignored = set(self.config["ignored_targets"])
        independent = set(self.config["independent_targets"])
        identities = self.config["site_identity"]
        anchors = {key[5:] for key in set(targets) | set(self.config["service_links"])
                   if key.startswith("site:") and self.resolve_target_id(key) in targets}
        domains = set(domains) | set(identities) | {key[5:] for key in known if key.startswith("site:")}
        domains.update(site[5:] for app in known if app.startswith("app:")
                       for site in [service_site_for_app(app[4:])] if site)
        changed = False
        for domain in sorted(domains, key=lambda value: (value.count("."), value)):
            site = "site:" + domain
            family = domain_family(domain)
            mode = self.config["subdomain_rules"].get(family, "smart")
            if not family or mode == "separate" or site in ignored | independent or site in self.config["service_links"]:
                continue
            web_apps = {key for key in known | ignored | independent
                        if key.startswith("app:") and service_site_for_app(key[4:]) == site}
            if web_apps & (ignored | independent):
                continue
            members = {alias for alias in self.config["service_links"] if self.resolve_target_id(alias) == site}
            if members & (ignored | independent):
                continue
            # Smart waits for the page's identity so a distinct web app is never folded in blindly.
            if mode == "smart" and domain not in identities:
                continue
            root = site_root(domain)
            own = targets.get(site)
            preferred = self.resolve_target_id(self.config["subdomain_destinations"].get(family, ""))
            candidates = []
            for anchor in anchors | ({domain} if own else set()):
                destination = self.resolve_target_id("site:" + anchor)
                if domain_family(anchor) != family or destination not in targets or destination in ignored:
                    continue
                if anchor != domain and mode == "smart":
                    if site_root(anchor) == root:
                        if self.distinct_service(domain, anchor) or (
                                own and own.get("category") != targets[destination].get("category")):
                            continue
                    elif not self.site_identity_matches(domain, anchor):
                        continue
                if "|".join(sorted((site, destination))) in self.config["dismissed_suggestions"]:
                    continue
                candidates.append((destination != preferred, site_root(anchor) != root,
                                   anchor != family, anchor.count("."), anchor, destination))
            if candidates:
                destination = min(candidates)[-1]
            else:
                # No saved entry yet: gather pending subdomains under one entry for Review.
                scope = family if mode == "group" else root
                destination = "site:" + scope
                if (own or not scope or scope == domain or destination in ignored
                        or self.resolve_target_id(destination) != destination
                        or (mode == "smart" and self.distinct_service(domain, scope))
                        or "|".join(sorted((site, destination))) in self.config["dismissed_suggestions"]):
                    continue
            if destination == site:
                continue
            self.store.merge_target(site, destination)
            targets.pop(site, None)
            for alias in members:
                self.config["service_links"][alias] = destination
            self.config["service_links"][site] = destination
            self.remember_auto_link(site)
            self.config["review_targets"] = [value for value in self.config["review_targets"] if value != site]
            changed = True
        if changed:
            save_config(self.config)

    def remember_auto_link(self, site: str) -> None:
        """Track links Focus made itself and keep at most AUTO_LINKS_MAX: the oldest is dropped,
        and made again if that subdomain is visited later. Manual merges are never dropped."""
        links, auto_links = self.config["service_links"], self.config["auto_links"]
        auto_links[:] = [value for value in auto_links if value in links and value != site] + [site]
        while len(auto_links) > AUTO_LINKS_MAX:
            oldest = auto_links.pop(0)
            destination = links.pop(oldest)
            for alias, target in list(links.items()):
                if target == oldest:
                    links[alias] = destination

    def known_site_domains(self) -> set[str]:
        """Sites with settings, links, history or an exclusion: the only ones worth naming."""
        config = self.config
        known = (set(config["targets"]) | set(config["service_links"]) | set(config["service_links"].values())
                 | self.store.target_ids() | set(config["ignored_targets"]) | set(config["review_targets"]))
        return {key[5:] for key in known if key.startswith("site:")}

    def prune_config(self) -> None:
        """Forget metadata and exceptions for entries with no settings, links or history left."""
        config = self.config
        known = (set(config["targets"]) | set(config["service_links"]) | set(config["service_links"].values())
                 | self.store.target_ids() | set(config["ignored_targets"]) | set(config["review_targets"]))
        visible = {canonical_domain(str(window.get("domain", ""))) for window in self.browser_windows.values()}
        keep = lambda domain: "site:" + domain in known or domain in visible
        before = json.dumps([config["site_identity"], config["site_names"], config["dismissed_suggestions"],
                             config["independent_targets"]], sort_keys=True)
        config["site_identity"] = {domain: value for domain, value in config["site_identity"].items() if keep(domain)}
        config["site_names"] = {domain: value for domain, value in config["site_names"].items() if keep(domain)}
        config["dismissed_suggestions"] = [key for key in config["dismissed_suggestions"]
                                           if all(part in known for part in key.split("|"))]
        config["independent_targets"] = [key for key in config["independent_targets"] if key in known]
        if json.dumps([config["site_identity"], config["site_names"], config["dismissed_suggestions"],
                       config["independent_targets"]], sort_keys=True) != before:
            save_config(config)

    def reconcile_targets(self, extra_app_ids: set[str] | None = None) -> None:
        """Fold linked app settings and usage into one service target."""
        history_ids = self.store.target_ids()
        # Grouping only needs to run when entries, links, identities or rules change.
        signature = hash((json.dumps([sorted(self.config["targets"]), self.config["service_links"],
                                      self.config["site_identity"], self.config["subdomain_rules"],
                                      self.config["ignored_targets"], self.config["independent_targets"],
                                      self.config["dismissed_suggestions"], self.config["review_targets"]],
                                     sort_keys=True), frozenset(history_ids), frozenset(extra_app_ids or ())))
        if signature == self.reconciled:
            return
        app_ids = {target_id for target_id in self.config["targets"] if target_id.startswith("app:")}
        app_ids.update(target_id for target_id in self.config["ignored_targets"] if target_id.startswith("app:"))
        app_ids.update(target_id for target_id in history_ids if target_id.startswith("app:"))
        app_ids.update(extra_app_ids or set())
        self.link_sites({site[5:] for app_id in (extra_app_ids or set())
                             if app_id not in self.config["independent_targets"]
                             for site in [service_site_for_app(app_id[4:])] if site})
        app_ids.update(key for key in self.config["service_links"] if key.startswith("app:"))
        changed = False
        ignored = set(self.config["ignored_targets"])
        for app_id in sorted(app_ids):
            destination = self.resolve_target_id(app_id)
            if destination == app_id:
                continue
            if self.config["service_links"].get(app_id) != destination:
                self.config["service_links"][app_id] = destination
                changed = True
            if app_id in self.config["targets"]:
                target = self.config["targets"].pop(app_id)
                if str(target.get("name", "")).casefold() == app_id[4:]:
                    target["name"] = destination[5:]
                self.config["targets"].setdefault(destination, target)
                changed = True
            if app_id in ignored:
                ignored.remove(app_id)
                if destination not in self.config["targets"]:
                    ignored.add(destination)
                changed = True
            if app_id in history_ids:
                self.store.merge_target(app_id, destination)
        if changed:
            self.config["ignored_targets"] = sorted(ignored)
            save_config(self.config)
        self.reconciled = None if changed else signature

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        op = message.get("op")
        with self.lock:
            if op == "browser_snapshot":
                windows = message.get("windows", [])
                windows = [window for window in windows[:BROWSER_ENTRIES_MAX] if isinstance(window, dict)
                           and browser_domain(window.get("domain"))] if isinstance(windows, list) else []
                browser_id = str(message.get("browser_id", "default"))[:100]
                snapshot_time = time.monotonic()
                self.browser_sessions[browser_id] = (snapshot_time, windows)
                self.browser_sessions = {key: value for key, value in self.browser_sessions.items()
                                         if snapshot_time - value[0] <= 3}
                self.browser_windows = {
                    key + ":" + str(window.get("id")): window
                    for key, (_, session_windows) in self.browser_sessions.items()
                    for window in session_windows
                    if isinstance(window, dict) and window.get("id") is not None and window.get("state") != "minimized"
                }
                metadata = message.get("site_metadata", [])
                metadata = metadata[:BROWSER_ENTRIES_MAX] if isinstance(metadata, list) and self.tracking else []
                # Names and identities are kept only while tracking, and only for sites on screen or
                # already in Focus: background tabs and paused browsing leave nothing on disk.
                visible_domains = {browser_domain(window.get("domain")) for window in self.browser_windows.values()}
                remembered = visible_domains | self.known_site_domains() if metadata or self.tracking else set()
                names_changed = False
                for window in (metadata + list(self.browser_windows.values())) if self.tracking else []:
                    if not isinstance(window, dict):
                        continue
                    domain = browser_domain(window.get("domain"))
                    if domain not in remembered or (domain not in self.config["site_identity"]
                                                    and len(self.config["site_identity"]) >= SITE_METADATA_MAX):
                        continue
                    name = clean_site_name(str(window.get("site_name", "")))[:120]
                    if domain and name and self.config["site_names"].get(domain) != name:
                        self.config["site_names"][domain] = name
                        names_changed = True
                    identity = window.get("site_identity")
                    if domain and isinstance(identity, dict):
                        application = " ".join(str(identity.get("application_name", "")).split())[:120]
                        manifest = str(identity.get("manifest", ""))[:2048]
                        try:
                            parsed = urllib.parse.urlsplit(manifest)
                            manifest_host = canonical_domain(parsed.hostname or "")
                            same_service = manifest_host and (manifest_host == domain or domain.endswith("." + manifest_host))
                            if parsed.scheme in ("http", "https") and same_service and not parsed.username and not parsed.password:
                                manifest = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                            else:
                                manifest = ""
                        except ValueError:
                            manifest = ""
                        value = {"application_name": application, "manifest": manifest}
                        if self.config["site_identity"].get(domain) != value:
                            self.config["site_identity"][domain] = value
                            names_changed = True
                if names_changed:
                    save_config(self.config)
                if self.tracking:
                    self.link_sites(visible_domains - {""})
                self.last_browser_snapshot = time.monotonic()
                blocked = self.blocked_domains()
                clients = visible_clients() if blocked else []
                blocked_tabs = [window["tab_id"] for window in windows
                                if isinstance(window, dict) and window.get("state") != "minimized"
                                and sum(other.get("title") == window.get("title") for other in self.browser_windows.values()) == 1
                                and window.get("tab_id") is not None
                                and canonical_domain(str(window.get("domain", ""))) in blocked
                                and self.visible_sites(clients, [window])]
                # Older bridges do not identify tabs; never let them close every
                # tab of a domain while the extension is awaiting an update.
                return {"ok": True, "blocked_domains": blocked if blocked_tabs else [],
                        "blocked_tab_ids": blocked_tabs}
            if op == "unlink":
                member = str(message.get("target_id", ""))
                group = self.resolve_target_id(member)
                links = self.config["service_links"]
                members = {group} | {alias for alias in links if self.resolve_target_id(alias) == group}
                if member not in members or len(members) < 2 or group not in self.config["targets"]:
                    return {"ok": False, "error": "target is not part of a saved group"}
                settings = dict(self.config["targets"][group])
                remaining = members - {member}
                destination = group if member != group else sorted(remaining)[0]
                # Flatten first so detaching a member never takes its aliases with it.
                for alias in members:
                    links.pop(alias, None)
                for alias in remaining - {destination}:
                    links[alias] = destination
                if member == group:
                    self.store.merge_target(group, destination)
                    self.config["targets"][destination] = dict(settings, name=target_display_name(destination))
                self.config["targets"][member] = dict(settings, name=target_display_name(member))
                independent = set(self.config["independent_targets"])
                independent.update((member, destination))
                self.config["independent_targets"] = sorted(independent)
                save_config(self.config)
                return {"ok": True}
            if op == "merge":
                source = self.resolve_target_id(str(message.get("source", "")))
                destination = self.resolve_target_id(str(message.get("destination", "")))
                targets = self.config["targets"]
                known_source = (source in targets or source in self.store.target_ids()
                                or source in self.config["review_targets"])
                if source == destination or destination not in targets or not known_source:
                    return {"ok": False, "error": "choose a known entry and a different saved destination"}
                if source not in targets:
                    self.store.classify_pending(source, targets[destination].get("category", "neutral"))
                self.store.merge_target(source, destination)
                targets.pop(source, None)
                for alias in list(self.config["service_links"]):
                    if self.resolve_target_id(alias) == source:
                        self.config["service_links"][alias] = destination
                self.config["service_links"][source] = destination
                self.config["auto_links"] = [value for value in self.config["auto_links"] if value != source]
                self.config["review_targets"] = [value for value in self.config["review_targets"] if value != source]
                self.config["link_schema"] = 2
                self.config["ignored_targets"] = [value for value in self.config["ignored_targets"]
                                                  if value not in (source, destination)]
                save_config(self.config)
                return {"ok": True}
            if op == "classify":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                category = str(message.get("category", "neutral"))
                if not target_id or not (target_id.startswith("app:") or target_id.startswith("site:")):
                    return {"ok": False, "error": "invalid target"}
                if category not in CATEGORIES:
                    return {"ok": False, "error": "invalid category"}
                target = self.config["targets"].setdefault(target_id, {"name": target_id.split(":", 1)[1]})
                if message.get("name"):
                    target["name"] = str(message["name"])
                target["category"] = category
                target.setdefault("quota_minutes", int(self.config["default_quota_minutes"]))
                self.config["review_targets"] = [value for value in self.config["review_targets"] if value != target_id]
                self.store.classify_pending(target_id, category)
                if target_id.startswith("site:"):
                    self.reconcile_targets()
                save_config(self.config)
                return {"ok": True}
            if op == "set_subdomain_rule":
                domain = canonical_domain(str(message.get("domain", "")))
                mode = str(message.get("mode", ""))
                target = self.resolve_target_id("site:" + domain)
                if not domain or target not in self.config["targets"] or mode not in ("smart", "group", "separate"):
                    return {"ok": False, "error": "invalid domain or subdomain mode"}
                members = {target} | {alias for alias in self.config["service_links"] if self.resolve_target_id(alias) == target}
                families = {domain_family(member[5:]) for member in members if member.startswith("site:")}
                families.add(domain_family(domain))
                for family in families - {""}:
                    self.config["subdomain_rules"][family] = mode
                    self.config["subdomain_destinations"][family] = target
                self.reconcile_targets()
                save_config(self.config)
                return {"ok": True}
            if op == "pause":
                duration = str(message.get("duration", "manual"))
                if duration not in {"manual", "15", "60", "tomorrow"}:
                    return {"ok": False, "error": "invalid pause duration"}
                now = dt.datetime.now().astimezone()
                self.paused = bool(message.get("paused"))
                self.pause_until = None
                if self.paused and duration == "tomorrow":
                    self.pause_until = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time()).astimezone().timestamp()
                elif self.paused and duration != "manual":
                    self.pause_until = now.timestamp() + int(duration) * 60
                self.config["pause_state"] = {"active": self.paused, "until": self.pause_until}
                save_config(self.config)
                return {"ok": True}
            if op == "snooze":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                target = self.config["targets"].get(target_id)
                status = self.limit_status(target_id, target, dt.datetime.now().astimezone()) if target else None
                if not status or not status["can_snooze"]:
                    return {"ok": False, "error": "no extension available for this entry"}
                self.config["snoozes"] = {key: value for key, value in self.config["snoozes"].items()
                                          if key in self.config["targets"]}
                self.config["snoozes"][target_id] = status["period_key"]
                save_config(self.config)
                return {"ok": True}
            if op == "focus":
                minutes = str(message.get("minutes", ""))
                if minutes not in FOCUS_SESSION_MINUTES | {"off"}:
                    return {"ok": False, "error": "focus session must be 25, 50, 90 or off"}
                until = None if minutes == "off" else time.time() + int(minutes) * 60
                self.config["focus_session"] = {"until": until}
                if until:
                    self.paused, self.pause_until = False, None
                    self.config["pause_state"] = {"active": False, "until": None}
                save_config(self.config)
                return {"ok": True}
            if op == "set_budget":
                try:
                    minutes = int(message.get("minutes"))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "budget must be a number of minutes"}
                if not 0 <= minutes <= MAX_DAILY_BUDGET_MINUTES:
                    return {"ok": False, "error": "budget must be 0–720 minutes"}
                self.config["daily_budget_minutes"] = minutes
                save_config(self.config)
                return {"ok": True}
            if op == "set_day_start":
                try:
                    hour = int(message.get("hour"))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "hour must be a number"}
                if not 0 <= hour <= MAX_DAY_START_HOUR:
                    return {"ok": False, "error": "day start must be 0–6"}
                self.config["day_start_hour"] = hour
                save_config(self.config)
                return {"ok": True}
            if op in ("apply_limit_suggestion", "dismiss_limit_suggestion"):
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                now = dt.datetime.now().astimezone()
                suggestion = next((item for item in self.limit_suggestions(self.tracking_date(now))
                                   if item["id"] == target_id), None)
                if not suggestion:
                    return {"ok": False, "error": "no limit suggestion for this entry"}
                if op == "dismiss_limit_suggestion":
                    self.config["dismissed_limit_suggestions"][target_id] = "%d-W%02d" % self.tracking_date(now).isocalendar()[:2]
                else:
                    target = self.config["targets"][target_id]
                    if target.get("limit_action") == "keep_open":
                        target["limit_action"] = "notify"
                    target.update({"category": "consumption", "limit_period": "day",
                                   "quota_minutes": suggestion["daily_minutes"]})
                save_config(self.config)
                return {"ok": True}
            if op == "set_weekly_summary":
                self.config["weekly_summary"] = bool(message.get("enabled"))
                save_config(self.config)
                return {"ok": True}
            if op == "set_limit_period":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                period = str(message.get("period", ""))
                target = self.config["targets"].get(target_id)
                if not target or period not in LIMIT_PERIODS:
                    return {"ok": False, "error": "invalid target or limit period"}
                if target.get("limit_period", "hour") != period:
                    # Keep the budget comparable: 10 min/hour over a day is far stricter than 10 min/day.
                    target["quota_minutes"] = 60 if period == "day" else DEFAULT_QUOTA_MINUTES
                target["limit_period"] = period
                save_config(self.config)
                return {"ok": True}
            if op == "set_warning":
                self.config["warn_before_limit"] = bool(message.get("enabled"))
                save_config(self.config)
                return {"ok": True}
            if op == "dismiss_suggestion":
                source, destination = str(message.get("source", "")), str(message.get("destination", ""))
                if source not in self.config["targets"] or destination not in self.config["targets"]:
                    return {"ok": False, "error": "unknown target"}
                key = "|".join(sorted((source, destination)))
                self.config["dismissed_suggestions"] = sorted(set(self.config["dismissed_suggestions"]) | {key})
                save_config(self.config)
                return {"ok": True}
            if op in {"export_history", "backup_settings", "clear_history"}:
                if op == "clear_history":
                    if message.get("confirm") is not True:
                        return {"ok": False, "error": "confirmation required"}
                    with self.store.db:
                        for table in ("daily_usage", "hourly_usage", "daily_screen_time"):
                            self.store.db.execute("DELETE FROM " + table)
                    self.notified_limits.clear()
                    self.warned_limits.clear()
                    self.last_data_action = {"message": "History cleared", "path": ""}
                else:
                    exports = STATE_DIR / "exports"
                    exports.mkdir(mode=0o700, exist_ok=True)
                    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    path = exports / (op + "-" + stamp + (".json" if op == "backup_settings" else ".csv"))
                    if op == "backup_settings":
                        atomic_json(path, self.config)
                    else:
                        with create_private(path) as output:
                            writer = csv.writer(output)
                            writer.writerow(["day", "target", "category", "seconds"])
                            def safe_cell(value):
                                return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value
                            for row in self.store.db.execute("SELECT day,target_id,category,seconds FROM daily_usage ORDER BY day,target_id"):
                                writer.writerow([safe_cell(value) for value in row])
                            for day, seconds in self.store.db.execute("SELECT day,seconds FROM daily_screen_time ORDER BY day"):
                                writer.writerow([day, "", "screen_time", seconds])
                    self.last_data_action = {"message": "History exported" if op == "export_history" else "Settings backed up",
                                             "path": str(path)}
                self.last_data_action["id"] = str(time.monotonic_ns())
                return {"ok": True, **self.last_data_action}
            if op == "set_schedule":
                try:
                    schedule = valid_schedule(message.get("schedule"))
                except ValueError as error:
                    return {"ok": False, "error": str(error)}
                self.config["schedule"] = schedule
                save_config(self.config)
                return {"ok": True}
            if op == "exclude":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                if not target_id.startswith(("app:", "site:")) or not target_id.split(":", 1)[1]:
                    return {"ok": False, "error": "invalid app or site"}
                ignored = set(self.config["ignored_targets"])
                ignored.add(target_id)
                self.config["review_targets"] = [value for value in self.config["review_targets"] if value != target_id]
                self.config["ignored_targets"] = sorted(ignored)
                if target_id not in self.config["targets"]:
                    self.store.forget_unclassified(target_id)
                save_config(self.config)
                return {"ok": True}
            if op == "unexclude":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                if not target_id.startswith(("app:", "site:")) or not target_id.split(":", 1)[1]:
                    return {"ok": False, "error": "invalid app or site"}
                if target_id not in self.config["targets"]:
                    self.config["review_targets"] = sorted(set(self.config["review_targets"]) | {target_id})
                self.config["ignored_targets"] = [value for value in self.config["ignored_targets"] if value != target_id]
                self.reconcile_targets()
                save_config(self.config)
                return {"ok": True}
            if op == "set_quota":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                target = self.config["targets"].get(target_id)
                if not target:
                    return {"ok": False, "error": "unknown target"}
                maximum = LIMIT_PERIODS.get(target.get("limit_period", "hour"), 120)
                try:
                    quota = max(1, min(maximum, int(message.get("quota_minutes"))))
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"quota must be 1–{maximum} minutes"}
                target["quota_minutes"] = quota
                save_config(self.config)
                return {"ok": True}
            if op == "set_limit_action":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                action = str(message.get("action", ""))
                target = self.config["targets"].get(target_id)
                if not target or action not in LIMIT_ACTIONS:
                    return {"ok": False, "error": "invalid target or limit action"}
                target["limit_action"] = action
                save_config(self.config)
                return {"ok": True}
            if op == "remove":
                self.config["targets"].pop(self.resolve_target_id(str(message.get("target_id", ""))), None)
                save_config(self.config)
                return {"ok": True}
            if op == "get_state":
                return {"ok": True, "state": self.latest_state}
        return {"ok": False, "error": "unknown operation"}

    def blocked_domains(self) -> list[str]:
        now = dt.datetime.now().astimezone()
        self.resume_if_due(now)
        locked, idle = session_status()
        if self.paused or locked or idle or not (in_work_hours(now, self.config["schedule"]) or self.focus_until(now)):
            return []
        blocked = []
        site_ids = {key for key in self.config["targets"] if key.startswith("site:")}
        site_ids.update(key for key in self.config["service_links"] if key.startswith("site:"))
        for site_id in sorted(site_ids):
            target_id = self.resolve_target_id(site_id)
            if target_id in self.config["ignored_targets"]:
                continue
            target = self.config["targets"].get(target_id, {})
            status = self.limit_status(target_id, target, now)
            if status and status["remaining"] == 0 and target.get("limit_action", "close") == "close":
                blocked.append(canonical_domain(site_id[5:]))
        return blocked

    def visible_sites(self, clients: list[dict[str, Any]], browser_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # The extension reports active tabs from non-minimized browser windows.
        # Match their title with a visible Hyprland client to exclude other workspaces.
        browser_clients = [client for client in clients if client["app_id"].casefold() in BROWSER_APP_IDS]
        sites: list[dict[str, Any]] = []
        for window in browser_windows:
            title = str(window.get("title", "")).casefold()
            if not title:
                continue
            matches = [client for client in browser_clients
                       if client["window_title"].casefold() == title
                       or any(client["window_title"].casefold().startswith(title + separator)
                              for separator in (" - ", " — ", " – "))]
            if len(matches) != 1 or sum(str(other.get("title", "")).casefold() == title
                                        for other in browser_windows) != 1:
                continue
            matched_client = matches[0]
            domain = canonical_domain(str(window.get("domain", "")))
            if domain:
                matched = domain
                sites.append({"target_id": "site:" + matched, "name": matched,
                              "address": matched_client["address"]})
        return sites

    def close_app_windows(self, clients: list[dict[str, Any]]) -> None:
        for client in clients:
            address = str(client.get("address", ""))
            if not address:
                continue
            try:
                window = "address:" + address
                command = "hl.dsp.window.close({ window = " + json.dumps(window) + " })"
                result = subprocess.run(["hyprctl", "dispatch", command],
                                        capture_output=True, timeout=1.0, check=False)
                if result.returncode != 0:
                    subprocess.run(["hyprctl", "dispatch", "closewindow", window],
                                   capture_output=True, timeout=1.0, check=False)
            except (OSError, subprocess.SubprocessError):
                pass

    def target_row(self, target_id: str, target: dict[str, Any], category: str, configured: bool,
                   now: dt.datetime) -> dict[str, Any]:
        status = self.limit_status(target_id, {**target, "category": category}, now) if configured else None
        return {
            "id": target_id,
            "name": target_display_name(target_id, target.get("name", "")),
            "category": category,
            "used_seconds": status["used"] if status else 0,
            "quota_seconds": int(target.get("quota_minutes", self.config["default_quota_minutes"])) * 60,
            "limit_period": status["period"] if status else target.get("limit_period", "hour"),
            "limit_action": target.get("limit_action", "close"),
            "remaining_seconds": status["remaining"] if status else None,
            "limit_reason": status["reason"] if status else "",
            "can_snooze": bool(status and status["can_snooze"] and status["remaining"] == 0),
            "visible_windows": 0,
            "configured": configured,
            "focused": False,
            "_status": status,
        }

    def tick(self, delta: float) -> None:
        now = dt.datetime.now().astimezone()
        with self.lock:
            self.resume_if_due(now)
            schedule = self.config["schedule"]
            paused = self.paused
            browser_active = time.monotonic() - self.last_browser_snapshot <= 3
            browser_windows = list(self.browser_windows.values()) if browser_active else []
        locked, idle = session_status()
        browser_running = browser_is_running()
        focus_active = bool(self.focus_until(now))
        in_schedule = (in_work_hours(now, schedule) or focus_active) and not locked and not idle and not paused
        app_clients = visible_clients() if in_schedule else []
        focused_address = focused_window_address() if in_schedule else ""
        visible = list(app_clients)
        site_clients = self.visible_sites(app_clients, browser_windows) if in_schedule else []
        visible.extend(site_clients)

        windows_to_close: list[dict[str, Any]] = []
        with self.lock:
            if not browser_running:
                self.browser_opened_at = None
            elif self.browser_opened_at is None:
                self.browser_opened_at = time.monotonic()
            browser_connection_expected = (browser_running and self.browser_opened_at is not None
                                           and time.monotonic() - self.browser_opened_at >= 8)
            in_schedule = in_schedule and not self.paused
            self.tracking = in_schedule
            if not in_schedule:
                visible = []
                site_clients = []
            targets = self.config["targets"]
            self.reconcile_targets({"app:" + client["app_id"].casefold() for client in app_clients})
            ignored_targets = set(self.config["ignored_targets"])
            bucket = current_hour_bucket(now)
            current = (bucket, "day:" + self.tracking_date(now).isoformat(), "focus:%s" % self.focus_until(now))
            self.notified_limits = {item for item in self.notified_limits if item[1].startswith(current)}
            self.warned_limits = {item for item in self.warned_limits if item[1].startswith(current)}
            day = self.tracking_date(now).isoformat()
            if self.store.last_pruned_day != now.date():
                self.store.prune(now)
                self.prune_config()
            ended = self.config["focus_session"].get("until")
            if ended and now.timestamp() >= ended:
                self.config["focus_session"] = {"until": None}
                save_config(self.config)
                self.notify("Focus session complete", "Limits are back to normal.")
            self.weekly_report(now)
            seen: dict[str, list[dict[str, Any]]] = {}
            site_addresses = {str(site.get("address") or "") for site in site_clients}
            for client in visible:
                if "target_id" not in client:
                    if client["app_id"].casefold() in BROWSER_APP_IDS and client["address"] in site_addresses:
                        continue
                    target_id = self.resolve_target_id("app:" + client["app_id"].casefold())
                    client = {**client, "target_id": target_id, "name": target_display_name(target_id)}
                else:
                    target_id = self.resolve_target_id(client["target_id"])
                if target_id in ignored_targets:
                    continue
                # A client opening endless windows with new ids cannot grow the state the shell parses.
                if target_id not in seen and len(seen) >= VISIBLE_ENTRIES_MAX:
                    continue
                seen.setdefault(target_id, []).append(client)

            categories = {}
            for target_id in seen:
                target = targets.get(target_id)
                category = target.get("category", "neutral") if target else "unclassified"
                categories[target_id] = category if category in CATEGORIES else ("neutral" if target else "unclassified")
            self.store.add_times(categories, delta, bucket, day)

            rows = []
            focus_until = self.focus_until(now)
            notice_key = lambda status: ("focus:%s" % focus_until if status["reason"] == "focus"
                                         else status["period_key"] + ":" + status["reason"])
            for target_id, clients in seen.items():
                configured = target_id in targets
                target = targets.get(target_id, {"name": clients[0].get("name") or target_id.split(":", 1)[1]})
                row = self.target_row(target_id, target, categories[target_id], configured, now)
                status = row.pop("_status")
                action = row["limit_action"]
                name = row["name"]
                if status and action != "keep_open":
                    key = (target_id, notice_key(status))
                    remaining = status["remaining"]
                    if (self.config["warn_before_limit"] and status["reason"] != "focus"
                            and 0 < remaining <= min(120, status["quota"] / 2) and key not in self.warned_limits):
                        self.warned_limits.add(key)
                        self.notify("Limit approaching · " + name,
                                    format_duration(max(60, remaining)) + " left " + ("today" if status["reason"] == "budget"
                                    or status["period"] == "day" else "this hour") + ".")
                    if remaining == 0:
                        if action == "close":
                            # The browser extension closes matching site tabs on its next snapshot.
                            windows_to_close.extend(client for client in clients
                                                    if client.get("app_id") and client["app_id"].casefold() not in BROWSER_APP_IDS)
                        if key not in self.notified_limits:
                            self.notified_limits.add(key)
                            title = {"focus": "Focus session · " + name + " is blocked",
                                     "budget": "Daily consumption budget reached"}.get(status["reason"], "Time limit reached · " + name)
                            body = name + (" closed." if action == "close" else " stays open.")
                            self.notify(title, body, target_id if status["can_snooze"] else "")
                            if status["can_snooze"]:
                                self.limit_prompts[target_id] = time.monotonic()
                row.update({"visible_windows": len(clients),
                            "focused": any(client.get("address") == focused_address for client in clients) and bool(focused_address)})
                rows.append(row)
            # Keep configured targets available after their windows are closed.
            for target_id, target in targets.items():
                if target_id in seen or target_id in ignored_targets:
                    continue
                category = target.get("category", "neutral")
                row = self.target_row(target_id, target, category if category in CATEGORIES else "neutral", True, now)
                row.pop("_status")
                rows.append(row)
            pending = self.store.pending_targets(REVIEW_DAYS)
            review_targets = set(self.config["review_targets"])
            for target_id in sorted(set(pending) | review_targets):
                if target_id in seen or target_id in targets or target_id in ignored_targets or self.resolve_target_id(target_id) != target_id:
                    continue
                if pending.get(target_id, 0) < REVIEW_MIN_SECONDS and target_id not in review_targets:
                    continue
                name = target_display_name(target_id)
                rows.append({
                    "id": target_id, "name": name, "category": "unclassified",
                    "used_seconds": 0, "quota_seconds": 0, "remaining_seconds": None,
                    "limit_action": "close",
                    "visible_windows": 0, "configured": False, "focused": False,
                })
            for row in rows:
                if row["id"].startswith("site:"):
                    domain = row["id"][5:]
                    row["name"] = clean_site_name(self.config["site_names"].get(domain) or domain)
            rows.sort(key=lambda row: row["name"].lower())
            usage_today = self.store.target_today(day)
            # Each link is resolved once here instead of once per entry.
            aliases: dict[str, set[str]] = {}
            for alias in self.config["service_links"]:
                aliases.setdefault(self.resolve_target_id(alias), set()).add(alias)
            for row in rows:
                row["today_seconds"] = int(usage_today.get(row["id"], 0))
                row["review"] = not row["configured"] and (
                    pending.get(row["id"], 0) >= REVIEW_MIN_SECONDS or row["id"] in review_targets)
                row["members"] = sorted({row["id"]} | aliases.get(row["id"], set()))
                row["linked"] = len(row["members"]) > 1
                families = sorted({domain_family(member[5:]) for member in row["members"] if member.startswith("site:")} - {""})
                row["grouping_scopes"] = families
                row["grouping_scope"] = domain_family(row["id"][5:]) if row["id"].startswith("site:") else (families[0] if families else "")
            labels = {}
            for target_id in {member for row in rows for member in row["members"]} | set(self.config["ignored_targets"]):
                saved = targets.get(target_id, {}).get("name", "")
                labels[target_id] = clean_site_name(self.config["site_names"].get(target_id[5:], "") if target_id.startswith("site:") else "") \
                    or target_display_name(target_id, saved)
            diagnostics = {"browser_connected": browser_active,
                           "browser_running": browser_running,
                           "browser_connection_expected": browser_connection_expected,
                           "browser_windows": len(browser_windows),
                           "browser_can_close_tabs": all(
                               window.get("tab_id") is not None for window in browser_windows
                           ) if browser_windows else None,
                           "matched_sites": len(site_clients)}
            # One status for bar and panel; "service_offline" is inferred by the widget from staleness.
            diagnostics["browser_status"] = (
                ("reload_extension" if diagnostics["browser_can_close_tabs"] is False else "connected") if browser_active
                else "browser_closed" if not browser_running
                else "browser_offline" if browser_connection_expected else "connecting")
            # Entries just stopped by a limit stay offered in Now for a short while,
            # even once their window or tab is closed.
            rows_by_id = {row["id"]: row for row in rows}
            self.limit_prompts = {key: when for key, when in self.limit_prompts.items()
                                  if time.monotonic() - when < LIMIT_PROMPT_SECONDS
                                  and rows_by_id.get(key, {}).get("can_snooze")}
            limit_prompts = [{"id": key, "name": rows_by_id[key]["name"]} for key in sorted(self.limit_prompts)]
            history = self.store.history(14)
            today = dict(history[-1]) if history and history[-1]["day"] == day else {"day": day}
            self.latest_state = {
                "updated_at": now.isoformat(timespec="seconds"),
                "diagnostics": diagnostics,
                "focus_until": self.focus_until(now),
                "daily_budget_minutes": self.config["daily_budget_minutes"],
                "budget_used_seconds": int(self.store.consumption_today(day)),
                "weekly_summary_enabled": self.config["weekly_summary"],
                "labels": labels,
                "limit_prompts": limit_prompts,
                "working": in_schedule,
                "paused": self.paused,
                "pause_until": self.pause_until,
                "warn_before_limit": self.config["warn_before_limit"],
                "weekly": self.weekly_summary(history, self.tracking_date(now)),
                "day_start_hour": self.config["day_start_hour"],
                "limit_suggestions": self.limit_suggestions(self.tracking_date(now)),
                "day_details": {
                    day_key: [{"id": target_id, "name": labels.get(target_id) or target_display_name(
                                   target_id, targets.get(target_id, {}).get("name", "")),
                               "category": category, "seconds": int(seconds)}
                              for target_id, category, seconds in entries]
                    for day_key, entries in self.store.day_breakdown(
                        (self.tracking_date(now) - dt.timedelta(days=6)).isoformat()).items()},
                "suggestions": self.group_suggestions(rows),
                "subdomain_rules": self.config["subdomain_rules"],
                "data_action": self.last_data_action,
                "idle": idle,
                "schedule": self.config["schedule"],
                "ignored_targets": self.config["ignored_targets"],
                "focused_id": next((row["id"] for row in rows if row["focused"] and row["id"].startswith("site:")),
                                   next((row["id"] for row in rows if row["focused"]), "")),
                "tracked": rows,
                "today": today,
                "history": history,
            }
            # Skip unchanged writes; the heartbeat lets the widget detect a stopped service.
            content = json.dumps({**self.latest_state, "updated_at": ""}, sort_keys=True)
            if content != self.written_state or time.monotonic() - self.written_at >= STATE_HEARTBEAT_SECONDS:
                atomic_json(STATE_PATH, self.latest_state, indent=None)
                self.written_state, self.written_at = content, time.monotonic()
        if windows_to_close:
            self.close_app_windows(windows_to_close)

    def run(self) -> None:
        # One daemon per user: a second one would take over the socket and overwrite settings.
        self.instance_lock = os.open(STATE_DIR / "daemon.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Focus is already running.", file=sys.stderr)
            raise SystemExit(1)
        server = ControlServer(str(SOCKET_PATH), self)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        focus_event = threading.Event()
        threading.Thread(target=self.watch_focus, args=(focus_event,), daemon=True).start()
        last = time.monotonic()
        # systemd stops the service with SIGTERM; exit through `finally` so batched usage is committed.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        try:
            while True:
                start = time.monotonic()
                delta = min(2.0, max(0.0, start - last))
                last = start
                try:
                    self.tick(delta)
                except Exception as error:  # one bad tick must not stop tracking
                    report = type(error).__name__
                    if report != self.last_tick_error or time.monotonic() - self.last_tick_error_at > 3600:
                        print(f"Focus tick failed: {report}", file=sys.stderr, flush=True)
                        self.last_tick_error, self.last_tick_error_at = report, time.monotonic()
                focus_event.wait(max(0.1, POLL_SECONDS - (time.monotonic() - start)))
                focus_event.clear()
        finally:
            with self.lock:
                self.store.flush(force=True)
            server.shutdown()
            server.server_close()

    def watch_focus(self, wakeup: threading.Event) -> None:
        runtime_dir = runtime_home()
        while True:
            sockets = list((runtime_dir / "hypr").glob("*/.socket2.sock"))
            if not sockets:
                time.sleep(2)
                continue
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(max(sockets, key=lambda path: path.stat().st_mtime)))
                    with client.makefile("r", encoding="utf-8", errors="replace") as stream:
                        for line in stream:
                            if line.startswith(("activewindowv2>>", "activewindow>>", "workspace>>")):
                                wakeup.set()
            except OSError:
                time.sleep(2)


class ControlHandler(socketserver.StreamRequestHandler):
    timeout = 5  # a client that never finishes its line must not hold a thread

    def handle(self) -> None:
        try:
            message = json.loads(self.rfile.readline(1024 * 1024).decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("request must be a JSON object")
            response = self.server.runtime.handle_message(message)  # type: ignore[attr-defined]
        except Exception:
            response = {"ok": False, "error": "invalid request"}
        try:
            self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            pass


class ControlServer(socketserver.ThreadingUnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: str, runtime: Runtime) -> None:
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        super().__init__(address, ControlHandler)
        self.runtime = runtime
        os.chmod(SOCKET_PATH, 0o600)


def request_agent(message: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(SOCKET_PATH))
        client.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        response = client.makefile("rb").readline(1024 * 1024)
    return json.loads(response.decode("utf-8"))


def native_host() -> None:
    """Chrome native-messaging bridge. One framed JSON request in, one out.

    A bad frame gets an error reply and the bridge keeps running, so no page can
    knock tracking offline by making the extension send something unexpected.
    """
    def reply(response: dict[str, Any]) -> None:
        encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(struct.pack("<I", len(encoded)) + encoded)
        sys.stdout.buffer.flush()

    try:
        while True:
            header = sys.stdin.buffer.read(4)
            if len(header) != 4:
                return
            length = struct.unpack("<I", header)[0]
            if length > 1024 * 1024:
                while length:  # skip the oversized frame without holding it in memory
                    chunk = sys.stdin.buffer.read(min(length, 65536))
                    if not chunk:
                        return
                    length -= len(chunk)
                reply({"ok": False, "error": "message too large"})
                continue
            payload = sys.stdin.buffer.read(length)
            if len(payload) != length:
                return
            try:
                request = json.loads(payload.decode("utf-8"))
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
            except (ValueError, RecursionError):
                reply({"ok": False, "error": "invalid message"})
                continue
            response = request_agent({"op": "get_state"} if request.get("op") == "status" else
                                     {"op": "browser_snapshot", "windows": request.get("windows", []),
                                      "browser_id": request.get("browser_id", "default"),
                                      "site_metadata": request.get("site_metadata", [])})
            reply({"ok": bool(response.get("ok"))} if request.get("op") == "status" else response)
    except (OSError, ValueError):
        return


OPERATIONS = ["classify", "quota", "limit-action", "remove", "add-app", "pause", "schedule", "exclude", "unexclude",
              "merge", "unlink", "warning", "dismiss-suggestion", "export-history", "backup-settings", "clear-history",
              "subdomains", "snooze", "focus", "budget", "day-start", "limit-suggestion", "weekly-summary", "limit-period"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Focus local tracking service")
    parser.add_argument("--daemon", action="store_true", help="run the local tracker")
    parser.add_argument("--native-host", action="store_true", help="run the Chromium native messaging bridge")
    parser.add_argument("--stdin", action="store_true",
                        help="read the operation and its arguments as one JSON array line on stdin")
    parser.add_argument("operation", nargs="?", choices=OPERATIONS)
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
    if args.stdin:
        # The panel passes app and site ids here: a command line is readable by other users in /proc.
        try:
            values = json.loads(sys.stdin.readline(65536))
        except ValueError:
            values = None
        if not (isinstance(values, list) and values and all(isinstance(value, str) for value in values)
                and values[0] in OPERATIONS):
            parser.error("--stdin expects a JSON array: an operation followed by its arguments")
        args.operation, args.arguments = values[0], values[1:]
    os.umask(0o077)  # history database, journals and anything else created stay owner-only
    ensure_dirs()
    if args.native_host:
        native_host()
        return 0
    if args.daemon:
        Runtime().run()
        return 0
    try:
        if args.operation == "classify" and len(args.arguments) == 2:
            target_id, category = args.arguments
            if category not in CATEGORIES:
                raise ValueError("category must be productive, neutral, or consumption")
            response = request_agent({"op": "classify", "target_id": target_id, "category": category})
        elif args.operation == "quota" and len(args.arguments) == 2:
            response = request_agent({"op": "set_quota", "target_id": args.arguments[0], "quota_minutes": args.arguments[1]})
        elif args.operation == "limit-action" and len(args.arguments) == 2:
            response = request_agent({"op": "set_limit_action", "target_id": args.arguments[0], "action": args.arguments[1]})
        elif args.operation == "subdomains" and len(args.arguments) == 2:
            response = request_agent({"op": "set_subdomain_rule", "domain": args.arguments[0], "mode": args.arguments[1]})
        elif args.operation == "unlink" and len(args.arguments) == 1:
            response = request_agent({"op": "unlink", "target_id": args.arguments[0]})
        elif args.operation == "merge" and len(args.arguments) == 2:
            response = request_agent({"op": "merge", "source": args.arguments[0], "destination": args.arguments[1]})
        elif args.operation == "remove" and len(args.arguments) == 1:
            response = request_agent({"op": "remove", "target_id": args.arguments[0]})
        elif args.operation == "pause" and len(args.arguments) == 1:
            value = args.arguments[0]
            if value not in {"on", "off", "15", "60", "tomorrow"}:
                raise ValueError("invalid pause duration")
            response = request_agent({"op": "pause", "paused": value != "off",
                                      "duration": value if value in {"15", "60", "tomorrow"} else "manual"})
        elif args.operation == "snooze" and len(args.arguments) == 1:
            response = request_agent({"op": "snooze", "target_id": args.arguments[0]})
        elif args.operation == "day-start" and len(args.arguments) == 1:
            response = request_agent({"op": "set_day_start", "hour": args.arguments[0]})
        elif args.operation == "limit-suggestion" and len(args.arguments) == 2 and args.arguments[1] in ("apply", "dismiss"):
            response = request_agent({"op": args.arguments[1] + "_limit_suggestion", "target_id": args.arguments[0]})
        elif args.operation == "focus" and len(args.arguments) == 1:
            response = request_agent({"op": "focus", "minutes": args.arguments[0]})
        elif args.operation == "budget" and len(args.arguments) == 1:
            response = request_agent({"op": "set_budget", "minutes": args.arguments[0]})
        elif args.operation == "weekly-summary" and args.arguments in (["on"], ["off"]):
            response = request_agent({"op": "set_weekly_summary", "enabled": args.arguments[0] == "on"})
        elif args.operation == "limit-period" and len(args.arguments) == 2:
            response = request_agent({"op": "set_limit_period", "target_id": args.arguments[0], "period": args.arguments[1]})
        elif args.operation == "warning" and len(args.arguments) == 1:
            response = request_agent({"op": "set_warning", "enabled": args.arguments[0] == "on"})
        elif args.operation == "dismiss-suggestion" and len(args.arguments) == 2:
            response = request_agent({"op": "dismiss_suggestion", "source": args.arguments[0], "destination": args.arguments[1]})
        elif args.operation in {"export-history", "backup-settings"} and not args.arguments:
            response = request_agent({"op": args.operation.replace("-", "_")})
        elif args.operation == "clear-history" and args.arguments == ["confirm"]:
            response = request_agent({"op": "clear_history", "confirm": True})
        elif args.operation == "schedule" and len(args.arguments) == 3:
            days, start, end = args.arguments
            response = request_agent({"op": "set_schedule", "schedule": {
                "weekdays": [int(day) for day in days.split(",") if day], "start": start, "end": end,
            }})
        elif args.operation in ("exclude", "unexclude") and len(args.arguments) == 1:
            response = request_agent({"op": args.operation, "target_id": args.arguments[0]})
        elif args.operation == "add-app" and len(args.arguments) in (1, 2):
            app_id = args.arguments[0].casefold()
            name = args.arguments[1] if len(args.arguments) == 2 else app_id
            response = request_agent({"op": "classify", "target_id": "app:" + app_id,
                                      "category": "neutral", "name": name})
        else:
            parser.print_help()
            return 2
        if not response.get("ok"):
            print(response.get("error", "request failed"), file=sys.stderr)
            return 1
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Focus request failed: {error}", file=sys.stderr)
        return 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
