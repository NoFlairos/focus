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
import datetime as dt
import functools
import json
import ipaddress
import os
import pathlib
import re
import socket
import socketserver
import sqlite3
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import Any


APP_NAME = "focus-ratio"
CATEGORIES = {"productive", "neutral", "consumption"}
LIMIT_ACTIONS = {"close", "notify", "keep_open"}
IGNORED_APP_IDS: set[str] = set()
DEFAULT_QUOTA_MINUTES = 10
POLL_SECONDS = 1.0
BROWSER_APP_IDS = {"chromium", "chromium-bin", "google-chrome", "google-chrome-stable", "chrome"}


@functools.lru_cache(maxsize=2)
def desktop_app_names(_refresh_period: int = 0) -> dict[str, str]:
    """Use installed desktop entries to turn window classes into application names."""
    names: dict[str, str] = {}
    roots = [pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share"))]
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
                        names.setdefault(key.casefold(), info["Name"])
            except (OSError, UnicodeError, configparser.Error, KeyError):
                continue
    return names


def app_display_name(app_id: str) -> str:
    # Desktop entries can appear or change while this user service stays alive.
    return desktop_app_names(int(time.monotonic() // 300)).get(app_id.casefold(), app_id)


def target_display_name(target_id: str, saved_name: str = "") -> str:
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


def config_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))


def state_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("XDG_STATE_HOME", pathlib.Path.home() / ".local/state"))


CONFIG_DIR = config_home() / APP_NAME
STATE_DIR = state_home() / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
STATE_PATH = STATE_DIR / "state.json"
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
        "hide_excluded": True,
        "hidden_excluded_targets": [],
        "service_links": {},
        "site_names": {},
        "site_identity": {},
        "subdomain_rules": {},
        "subdomain_destinations": {},
        "subdomain_rule_schema": 2,
        "link_schema": 2,
        "independent_targets": [],
        "warn_before_limit": True,
        "dismissed_suggestions": [],
        "pause_state": {"active": False, "until": None},
    }


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


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
        return value
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


def atomic_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)


def save_config(value: dict[str, Any]) -> None:
    atomic_json(CONFIG_PATH, value)


def hypr_json(command: str) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(["hyprctl", "-j", command], capture_output=True, text=True, timeout=1.5, check=True)
        parsed = json.loads(result.stdout)
        return parsed if isinstance(parsed, list) else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def focused_window_address() -> str:
    try:
        result = subprocess.run(["hyprctl", "-j", "activewindow"], capture_output=True,
                                text=True, timeout=1.5, check=True)
        return str(json.loads(result.stdout).get("address") or "")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AttributeError):
        return ""


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
        app_id = str(client.get("class") or client.get("initialClass") or "").strip()
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
    roots = [pathlib.Path(os.environ.get("XDG_DATA_HOME", pathlib.Path.home() / ".local/share"))]
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


def session_status() -> tuple[bool, bool]:
    session_id = os.environ.get("XDG_SESSION_ID")
    if not session_id:
        return False, False
    try:
        result = subprocess.run(
            ["loginctl", "show-session", session_id, "--property=LockedHint", "--property=IdleHint"],
            capture_output=True, text=True, timeout=0.8, check=True,
        )
        flags = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return flags.get("LockedHint", "").lower() == "yes", flags.get("IdleHint", "").lower() == "yes"
    except (OSError, subprocess.SubprocessError):
        return False, False


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
        with self.db:
            self.db.execute("""
                INSERT INTO daily_screen_time(day,seconds,started_at) VALUES(?,?,?)
                ON CONFLICT(day) DO UPDATE SET seconds=seconds+excluded.seconds
            """, (day, max(0.0, seconds) if categories else 0.0,
                  dt.datetime.now().astimezone().isoformat(timespec="seconds")))
        if seconds <= 0 or not categories:
            return
        with self.db:
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

    def target_today(self, day: str) -> dict[str, float]:
        rows = self.db.execute("SELECT target_id, SUM(seconds) FROM daily_usage WHERE day=? GROUP BY target_id", (day,)).fetchall()
        return {target_id: float(seconds) for target_id, seconds in rows}

    def pending_targets(self) -> list[str]:
        start = (dt.date.today() - dt.timedelta(days=29)).isoformat()
        rows = self.db.execute("SELECT DISTINCT target_id FROM daily_usage WHERE category='unclassified' AND day>=?", (start,)).fetchall()
        return [str(row[0]) for row in rows]

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


@functools.lru_cache(maxsize=2048)
def domain_family(domain: str) -> str:
    """Return the registrable ICANN domain, including hosted sibling projects."""
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
        suffix = ".".join(labels[index:])
        # ICANN rules define the domain family. Private hosting boundaries
        # must not prevent an explicitly selected Group from joining siblings.
        if library.psl_is_public_suffix2(context, suffix.encode("utf-8"), 1):
            return ".".join(labels[index - 1:]) if index else ""
    return domain


class Runtime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
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
        self.migrate_subdomain_rules()
        self.reconcile_targets()
        self.browser_sessions: dict[str, tuple[float, list]] = {}
        self.browser_windows: dict[str, dict[str, Any]] = {}
        self.last_browser_snapshot = 0.0
        self.browser_opened_at: float | None = None
        self.paused = bool(self.config["pause_state"].get("active"))
        self.pause_until = self.config["pause_state"].get("until")
        self.warned_limits: set[tuple[str, str]] = set()
        self.last_data_action: dict[str, Any] = {}
        self.notified_limits: set[tuple[str, str]] = set()
        self.latest_state: dict[str, Any] = {"tracked": [], "today": {}, "history": []}

    def resume_if_due(self, now: dt.datetime) -> None:
        if self.paused and self.pause_until and now.timestamp() >= self.pause_until:
            self.paused = False
            self.pause_until = None
            self.config["pause_state"] = {"active": False, "until": None}
            save_config(self.config)

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
        # Detachment prevents automatic linking, not suggestions for manual review.
        candidates = [row for row in rows if row["configured"]]

        def domains(row: dict) -> set[str]:
            found = set()
            for member in set(row.get("members", [])) | {row["id"]}:
                site = ""
                if member.startswith("site:"):
                    site = member
                elif member.startswith("app:"):
                    site = service_site_for_app(member[4:])
                if site:
                    found.add(canonical_domain(site[5:]))
            return found

        suggestions = []
        site_domains = {row["id"]: domains(row) for row in candidates}
        for index, source in enumerate(candidates):
            name = re.sub(r"[^\w]", "", source["name"].casefold())
            for destination in candidates[index + 1:]:
                key = "|".join(sorted((source["id"], destination["id"])))
                if key in self.config["dismissed_suggestions"]:
                    continue
                related = []
                for first in site_domains[source["id"]]:
                    for second in site_domains[destination["id"]]:
                        if first.endswith("." + second):
                            related.append((first, second, source, destination))
                        elif second.endswith("." + first):
                            related.append((second, first, destination, source))
                if related:
                    # Keep the parent group's settings; prefer the closest parent.
                    child, parent, child_row, parent_row = min(
                        related, key=lambda item: (item[0].count(".") - item[1].count("."), item[0], item[1]))
                    priority = 0 if child_row.get("category") == parent_row.get("category") else 1
                    suggestions.append((priority, {"source": child_row["id"], "destination": parent_row["id"],
                        "name": parent, "reason": "Subdomain", "source_domain": child, "destination_domain": parent}))
                elif len(name) >= 3 and name == re.sub(r"[^\w]", "", destination["name"].casefold()):
                    suggestions.append((2, {"source": source["id"], "destination": destination["id"],
                                        "name": source["name"], "reason": "Matching names"}))
        suggestions.sort(key=lambda item: (item[0], item[1]["destination"], item[1]["source"]))
        return [suggestion for _, suggestion in suggestions[:8]]

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

    def link_sites(self, domains: set[str]) -> None:
        """Group sibling sites within a domain family; Smart requires shared identity."""
        targets = self.config["targets"]
        known = set(targets) | self.store.target_ids() | set(self.config["review_targets"])
        ignored = set(self.config["ignored_targets"])
        independent = set(self.config["independent_targets"])
        anchors = {key[5:] for key in set(targets) | set(self.config["service_links"])
                   if key.startswith("site:") and self.resolve_target_id(key) in targets}
        domains = set(domains) | set(self.config["site_identity"]) | {key[5:] for key in known if key.startswith("site:")}
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
            preferred = self.resolve_target_id(self.config["subdomain_destinations"].get(family, ""))
            candidates = []
            for anchor in anchors | ({domain} if site in targets else set()):
                destination = self.resolve_target_id("site:" + anchor)
                if domain_family(anchor) != family or destination not in targets or destination in ignored:
                    continue
                if mode == "smart" and anchor != domain and not self.site_identity_matches(domain, anchor):
                    continue
                key = "|".join(sorted((site, destination)))
                if key in self.config["dismissed_suggestions"]:
                    continue
                candidates.append((destination != preferred, anchor != family, anchor.count("."), anchor, destination))
            if not candidates:
                continue
            destination = min(candidates)[-1]
            if destination == site:
                continue
            self.store.merge_target(site, destination)
            targets.pop(site, None)
            for alias in members:
                self.config["service_links"][alias] = destination
            self.config["service_links"][site] = destination
            self.config["review_targets"] = [value for value in self.config["review_targets"] if value != site]
            changed = True
        if changed:
            save_config(self.config)

    def reconcile_targets(self, extra_app_ids: set[str] | None = None) -> None:
        """Fold linked app settings and usage into one service target."""
        history_ids = self.store.target_ids()
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

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        op = message.get("op")
        with self.lock:
            if op == "browser_snapshot":
                windows = message.get("windows", [])
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
                if not isinstance(metadata, list):
                    metadata = []
                names_changed = False
                for window in metadata + list(self.browser_windows.values()):
                    if not isinstance(window, dict):
                        continue
                    domain = canonical_domain(str(window.get("domain", "")))
                    name = " ".join(str(window.get("site_name", "")).split())[:120]
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
                self.link_sites({canonical_domain(str(window.get("domain", "")))
                                     for window in self.browser_windows.values() if window.get("domain")})
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
            if op == "set_excluded_entry_visibility":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                hidden = message.get("hidden")
                if target_id not in self.config["ignored_targets"] or not isinstance(hidden, bool):
                    return {"ok": False, "error": "choose an excluded entry and a boolean visibility"}
                targets = set(self.config["hidden_excluded_targets"])
                if hidden:
                    targets.add(target_id)
                else:
                    targets.discard(target_id)
                self.config["hidden_excluded_targets"] = sorted(targets)
                save_config(self.config)
                return {"ok": True}
            if op == "set_excluded_visibility":
                hidden = message.get("hidden")
                if not isinstance(hidden, bool):
                    return {"ok": False, "error": "hidden must be a boolean"}
                self.config["hide_excluded"] = hidden
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
                        with path.open("x", encoding="utf-8", newline="") as output:
                            os.chmod(path, 0o600)
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
                self.config["hidden_excluded_targets"] = [value for value in self.config["hidden_excluded_targets"] if value != target_id]
                self.config["ignored_targets"] = [value for value in self.config["ignored_targets"] if value != target_id]
                self.reconcile_targets()
                save_config(self.config)
                return {"ok": True}
            if op == "set_quota":
                target_id = self.resolve_target_id(str(message.get("target_id", "")))
                try:
                    quota = max(1, min(120, int(message.get("quota_minutes"))))
                except (TypeError, ValueError):
                    return {"ok": False, "error": "quota must be 1–120 minutes"}
                target = self.config["targets"].get(target_id)
                if not target:
                    return {"ok": False, "error": "unknown target"}
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
        if self.paused or locked or idle or not in_work_hours(now, self.config["schedule"]):
            return []
        bucket = current_hour_bucket(now)
        blocked = []
        site_ids = {key for key in self.config["targets"] if key.startswith("site:")}
        site_ids.update(key for key in self.config["service_links"] if key.startswith("site:"))
        for site_id in sorted(site_ids):
            target_id = self.resolve_target_id(site_id)
            if target_id in self.config["ignored_targets"]:
                continue
            target = self.config["targets"].get(target_id, {})
            if target.get("category") == "consumption" and target.get("limit_action", "close") == "close":
                quota = int(target.get("quota_minutes", self.config["default_quota_minutes"])) * 60
                if self.store.used_this_hour(target_id, bucket) >= quota:
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
        in_schedule = in_work_hours(now, schedule) and not locked and not idle and not paused
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
            if not in_schedule:
                visible = []
                site_clients = []
            targets = self.config["targets"]
            self.reconcile_targets({"app:" + client["app_id"].casefold() for client in app_clients})
            ignored_targets = set(self.config["ignored_targets"])
            bucket = current_hour_bucket(now)
            self.notified_limits = {item for item in self.notified_limits if item[1] == bucket}
            self.warned_limits = {item for item in self.warned_limits if item[1] == bucket}
            day = now.date().isoformat()
            self.store.prune(now)
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
                seen.setdefault(target_id, []).append(client)

            categories = {}
            for target_id in seen:
                target = targets.get(target_id)
                category = target.get("category", "neutral") if target else "unclassified"
                categories[target_id] = category if category in CATEGORIES else ("neutral" if target else "unclassified")
            self.store.add_times(categories, delta, bucket, day)

            rows = []
            for target_id, clients in seen.items():
                configured = target_id in targets
                target = targets.get(target_id, {"name": clients[0].get("name") or target_id.split(":", 1)[1]})
                category = categories[target_id]
                quota = int(target.get("quota_minutes", self.config["default_quota_minutes"])) * 60
                used = self.store.used_this_hour(target_id, bucket) if category == "consumption" and configured else 0
                remaining = max(0, quota - int(used)) if category == "consumption" and configured else None
                action = target.get("limit_action", "close")
                warning_at = min(120, quota / 2)
                if (self.config["warn_before_limit"] and category == "consumption" and action != "keep_open"
                        and remaining is not None and 0 < remaining <= warning_at
                        and (target_id, bucket) not in self.warned_limits):
                    self.warned_limits.add((target_id, bucket))
                    try:
                        name = self.config["site_names"].get(target_id[5:], target_display_name(target_id, target.get("name", "")))
                        subprocess.Popen(["notify-send", "-a", "Focus", "Limit approaching · " + name,
                                          str(remaining) + " seconds left this hour."],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except OSError:
                        pass
                if category == "consumption" and remaining == 0:
                    if action == "close":
                        windows_to_close.extend(client for client in clients
                                                if client.get("app_id") and client["app_id"].casefold() not in BROWSER_APP_IDS)
                    elif action == "notify" and (target_id, bucket) not in self.notified_limits:
                        self.notified_limits.add((target_id, bucket))
                        try:
                            app_name = target_display_name(target_id, target.get("name", ""))
                            subprocess.Popen(["notify-send", "-a", "Focus",
                                              "-i", "preferences-system-time",
                                              "Time limit reached · " + app_name,
                                              "Your " + str(quota // 60) + " min hourly limit is up. "
                                              + app_name + " stays open."],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except OSError:
                            pass
                    # The browser extension closes matching site tabs on its next
                    # native-messaging snapshot and prevents navigation until reset.
                rows.append({
                    "id": target_id,
                    "name": target_display_name(target_id, target.get("name", "")),
                    "category": category,
                    "used_seconds": int(used),
                    "quota_seconds": quota,
                    "limit_action": action,
                    "remaining_seconds": remaining,
                    "visible_windows": len(clients),
                    "configured": configured,
                    "focused": any(client.get("address") == focused_address for client in clients) and bool(focused_address),
                })
            # Keep configured targets available after their windows are closed.
            for target_id, target in targets.items():
                if target_id in seen or target_id in ignored_targets:
                    continue
                category = target.get("category", "neutral")
                if category not in CATEGORIES:
                    category = "neutral"
                quota = int(target.get("quota_minutes", self.config["default_quota_minutes"])) * 60
                used = self.store.used_this_hour(target_id, bucket) if category == "consumption" else 0
                rows.append({
                    "id": target_id,
                    "name": target_display_name(target_id, target.get("name", "")),
                    "category": category,
                    "used_seconds": int(used),
                    "quota_seconds": quota,
                    "limit_action": target.get("limit_action", "close"),
                    "remaining_seconds": max(0, quota - int(used)) if category == "consumption" else None,
                    "visible_windows": 0,
                    "configured": True,
                    "focused": False,
                })
            for target_id in sorted(set(self.store.pending_targets()) | set(self.config["review_targets"])):
                if target_id in seen or target_id in targets or target_id in ignored_targets or self.resolve_target_id(target_id) != target_id:
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
                    row["name"] = self.config["site_names"].get(domain) or domain
            rows.sort(key=lambda row: row["name"].lower())
            usage_today = self.store.target_today(day)
            for row in rows:
                row["today_seconds"] = int(usage_today.get(row["id"], 0))
                row["members"] = sorted({row["id"]} | {alias for alias in self.config["service_links"]
                                                       if self.resolve_target_id(alias) == row["id"]})
                row["linked"] = len(row["members"]) > 1
                families = sorted({domain_family(member[5:]) for member in row["members"] if member.startswith("site:")} - {""})
                row["grouping_scopes"] = families
                row["grouping_scope"] = domain_family(row["id"][5:]) if row["id"].startswith("site:") else (families[0] if families else "")
            history = self.store.history(30)
            today = dict(history[-1]) if history and history[-1]["day"] == day else {"day": day}
            self.latest_state = {
                "updated_at": now.isoformat(timespec="seconds"),
                "diagnostics": {"browser_connected": browser_active,
                                "browser_running": browser_running,
                                "browser_connection_expected": browser_connection_expected,
                                "browser_windows": len(browser_windows),
                                "browser_can_close_tabs": all(
                                    window.get("tab_id") is not None for window in browser_windows
                                ) if browser_windows else None,
                                "matched_sites": len(site_clients)},
                "working": in_schedule,
                "paused": self.paused,
                "pause_until": self.pause_until,
                "warn_before_limit": self.config["warn_before_limit"],
                "weekly": self.weekly_summary(history, now.date()),
                "suggestions": self.group_suggestions(rows),
                "subdomain_rules": self.config["subdomain_rules"],
                "data_action": self.last_data_action,
                "idle": idle,
                "schedule": self.config["schedule"],
                "ignored_targets": self.config["ignored_targets"],
                "hide_excluded": self.config["hide_excluded"],
                "hidden_excluded_targets": self.config["hidden_excluded_targets"],
                "focused_id": next((row["id"] for row in rows if row["focused"] and row["id"].startswith("site:")),
                                   next((row["id"] for row in rows if row["focused"]), "")),
                "tracked": rows,
                "today": today,
                "history": history,
            }
            atomic_json(STATE_PATH, self.latest_state)
        if windows_to_close:
            self.close_app_windows(windows_to_close)

    def run(self) -> None:
        server = ControlServer(str(SOCKET_PATH), self)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        focus_event = threading.Event()
        threading.Thread(target=self.watch_focus, args=(focus_event,), daemon=True).start()
        last = time.monotonic()
        try:
            while True:
                start = time.monotonic()
                delta = min(2.0, max(0.0, start - last))
                last = start
                self.tick(delta)
                focus_event.wait(max(0.1, POLL_SECONDS - (time.monotonic() - start)))
                focus_event.clear()
        finally:
            server.shutdown()
            server.server_close()

    def watch_focus(self, wakeup: threading.Event) -> None:
        runtime_dir = pathlib.Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
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
    def handle(self) -> None:
        try:
            line = self.rfile.readline(1024 * 1024)
            message = json.loads(line.decode("utf-8"))
            response = self.server.runtime.handle_message(message)  # type: ignore[attr-defined]
            self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as error:
            self.wfile.write((json.dumps({"ok": False, "error": str(error)}) + "\n").encode("utf-8"))


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
    """Chrome native-messaging bridge. One framed JSON request in, one out."""
    try:
        while True:
            header = sys.stdin.buffer.read(4)
            if len(header) != 4:
                return
            length = struct.unpack("<I", header)[0]
            if length > 1024 * 1024:
                return
            payload = sys.stdin.buffer.read(length)
            if len(payload) != length:
                return
            request = json.loads(payload.decode("utf-8"))
            response = request_agent({"op": "get_state"} if request.get("op") == "status" else
                                     {"op": "browser_snapshot", "windows": request.get("windows", []),
                                      "browser_id": request.get("browser_id", "default"),
                                      "site_metadata": request.get("site_metadata", [])})
            if request.get("op") == "status":
                response = {"ok": bool(response.get("ok"))}
            encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
            sys.stdout.buffer.write(struct.pack("<I", len(encoded)) + encoded)
            sys.stdout.buffer.flush()
    except (OSError, json.JSONDecodeError, KeyError):
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Focus local tracking service")
    parser.add_argument("--daemon", action="store_true", help="run the local tracker")
    parser.add_argument("--native-host", action="store_true", help="run the Chromium native messaging bridge")
    parser.add_argument("operation", nargs="?", choices=["classify", "quota", "limit-action", "remove", "add-app", "pause", "schedule", "exclude", "unexclude", "merge", "unlink", "warning", "dismiss-suggestion", "export-history", "backup-settings", "clear-history", "subdomains", "excluded-visibility", "excluded-entry-visibility"])
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args()
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
        elif args.operation == "excluded-entry-visibility" and len(args.arguments) == 2 and args.arguments[1] in ("show", "hide"):
            response = request_agent({"op": "set_excluded_entry_visibility", "target_id": args.arguments[0], "hidden": args.arguments[1] == "hide"})
        elif args.operation == "excluded-visibility" and args.arguments in (["show"], ["hide"]):
            response = request_agent({"op": "set_excluded_visibility", "hidden": args.arguments[0] == "hide"})
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
