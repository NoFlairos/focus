"""Regression checks for Focus Ratio's local accounting and window matching."""

import datetime as dt
import importlib.util
import pathlib
import tempfile
import time
import unittest
from unittest import mock


AGENT_PATH = pathlib.Path(__file__).resolve().parents[1] / "agent" / "focus_ratio_agent.py"
spec = importlib.util.spec_from_file_location("focus_ratio_agent", AGENT_PATH)
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
ORIGINAL_VISIBLE_CLIENTS = agent.visible_clients
ORIGINAL_IN_WORK_HOURS = agent.in_work_hours


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = pathlib.Path(self.temp.name)
        self.paths = mock.patch.multiple(
            agent,
            CONFIG_DIR=root / "config",
            STATE_DIR=root / "state",
            CONFIG_PATH=root / "config" / "config.json",
            STATE_PATH=root / "state" / "state.json",
            DB_PATH=root / "state" / "history.sqlite3",
            SOCKET_PATH=root / "state" / "control.sock",
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.clients = [{"app_id": "Test", "window_title": "Test", "address": "0x123"}]
        self.visible = mock.patch.object(agent, "visible_clients", lambda: self.clients)
        self.focus = mock.patch.object(agent, "focused_window_address", lambda: "0x123")
        self.session = mock.patch.object(agent, "session_status", lambda: (False, False))
        self.schedule = mock.patch.object(agent, "in_work_hours", lambda now, schedule: True)
        for patcher in (self.visible, self.focus, self.session, self.schedule):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runtime = agent.Runtime()
        self.addCleanup(lambda: self.runtime.store.db.close())
        self.closed = []
        self.runtime.close_app_windows = self.closed.extend

    def test_app_name_comes_from_desktop_metadata(self):
        data = pathlib.Path(self.temp.name) / "data" / "applications"
        data.mkdir(parents=True)
        (data / "sample.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Sample Editor\nStartupWMClass=odd.window.Class\n")
        agent.desktop_app_names.cache_clear()
        self.addCleanup(agent.desktop_app_names.cache_clear)
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(data.parent), "XDG_DATA_DIRS": ""}):
            self.assertEqual(agent.app_display_name("odd.window.Class"), "Sample Editor")
            self.assertEqual(agent.app_display_name("unknown.app"), "unknown.app")
            self.assertEqual(agent.target_display_name("app:odd.window.Class"), "Sample Editor")
            self.assertEqual(agent.target_display_name("app:chrome-x.com__-default"), "x.com")
            self.assertEqual(agent.target_display_name("app:chrome-youtube.com__-default"), "youtube.com")
            self.assertEqual(agent.target_display_name("app:odd.window.Class", "My App"), "My App")

    def test_site_names_preserve_service_identity(self):
        self.assertEqual(agent.target_display_name("site:console.cloud.google.com"), "console.cloud.google.com")
        self.assertEqual(agent.target_display_name("site:accounts.google.com"), "accounts.google.com")
        self.assertEqual(agent.target_display_name("site:unknown.google.com"), "unknown.google.com")
        self.assertEqual(agent.target_display_name("site:preview-one.pages.dev"), "preview-one.pages.dev")
        self.assertEqual(agent.target_display_name("site:preview-two.pages.dev"), "preview-two.pages.dev")
        self.assertEqual(agent.target_display_name("site:example.co.uk"), "example.co.uk")
        self.assertEqual(agent.target_display_name("site:example.com", "My workspace"), "My workspace")

    def test_browser_site_requires_matching_browser_window(self):
        windows = [{"title": "A post", "domain": "x.com"}]
        unrelated = [{"app_id": "foot", "window_title": "A post", "address": "0x999"}]
        self.assertEqual(self.runtime.visible_sites(unrelated, windows), [])
        browser = [{"app_id": "chromium", "window_title": "A post - Chromium", "address": "0x456"}]
        self.assertEqual(self.runtime.visible_sites(browser, windows), [
            {"target_id": "site:x.com", "name": "x.com", "address": "0x456"}
        ])
        self.assertEqual(self.runtime.visible_sites(browser, [{"title": "A post", "domain": "sub.x.com"}])[0]["target_id"], "site:sub.x.com")
        self.assertEqual(self.runtime.visible_sites(browser, [{"title": "", "domain": "x.com"}]), [])

    def test_google_parent_does_not_capture_gmail_or_cloud(self):
        clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": "0x123"}]
        for domain in ("mail.google.com", "console.cloud.google.com", "google.com"):
            sites = self.runtime.visible_sites(clients, [{"title": "Inbox", "domain": domain}])
            self.assertEqual(sites[0]["target_id"], "site:" + domain)
        self.assertEqual(agent.service_site_for_app("chrome-mail.google.com__-default"), "site:mail.google.com")

    def test_manual_merge_shares_usage_and_preserves_destination_settings(self):
        for target in ("site:first.example", "app:test"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": "app:test", "quota_minutes": 7})
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        self.runtime.store.add_times({"site:first.example": "consumption"}, 20, bucket, now.date().isoformat())
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "app:test"})["ok"])
        self.clients.append({"app_id": "google-chrome", "window_title": "Inbox - Google Chrome", "address": "0x456"})
        self.runtime.browser_windows = {"1": {"title": "Inbox", "domain": "first.example"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(10)
        rows = self.runtime.latest_state["tracked"]
        self.assertEqual([row["id"] for row in rows], ["app:test"])
        self.assertEqual(rows[0]["used_seconds"], 30)
        self.assertEqual(rows[0]["quota_seconds"], 420)
        self.assertEqual(rows[0]["members"], ["app:test", "site:first.example"])
        self.assertFalse(self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "app:test"})["ok"])
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id("site:first.example"), "app:test")
        self.assertEqual(self.runtime.store.used_this_hour("app:test", bucket), 30)

    def test_group_merges_flatten_links_without_cycles(self):
        for target in ("app:a", "app:b", "site:c.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        for source, destination in (("app:a", "app:b"), ("app:b", "site:c.example")):
            self.assertTrue(self.runtime.handle_message({"op": "merge", "source": source, "destination": destination})["ok"])
        self.assertEqual(self.runtime.resolve_target_id("app:a"), "site:c.example")
        self.assertEqual(self.runtime.resolve_target_id("app:b"), "site:c.example")
        self.assertEqual(set(self.runtime.config["targets"]), {"site:c.example"})

    def test_blocking_respects_pause_schedule_idle_and_visible_tabs(self):
        target = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({target: "consumption"}, 601, agent.current_hour_bucket(now), now.date().isoformat())
        self.assertEqual(self.runtime.blocked_domains(), ["example.org"])
        self.runtime.paused = True
        self.assertEqual(self.runtime.blocked_domains(), [])
        self.runtime.paused = False
        with mock.patch.object(agent, "in_work_hours", return_value=False):
            self.assertEqual(self.runtime.blocked_domains(), [])
        with mock.patch.object(agent, "session_status", return_value=(False, True)):
            self.assertEqual(self.runtime.blocked_domains(), [])
        self.clients = [{"app_id": "google-chrome", "window_title": "Visible - Google Chrome", "address": "0x1"}]
        response = self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {"id": 1, "tab_id": 10, "title": "Visible", "domain": "example.org"},
            {"id": 2, "tab_id": 20, "title": "Elsewhere", "domain": "example.org"}]})
        self.assertEqual(response["blocked_tab_ids"], [10])

    def test_ambiguous_browser_titles_are_not_assigned(self):
        clients = [{"app_id": "chromium", "window_title": "Inbox - Chromium", "address": address}
                   for address in ("0x1", "0x2")]
        self.assertEqual(self.runtime.visible_sites(clients, [{"title": "Inbox", "domain": "example.org"}]), [])

    def test_merged_sites_share_blocking_and_browser_sessions_coexist(self):
        for target in ("site:first.example", "site:second.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "merge", "source": "site:first.example", "destination": "site:second.example"})
        now = dt.datetime.now().astimezone()
        self.runtime.store.add_times({"site:second.example": "consumption"}, 601,
                                     agent.current_hour_bucket(now), now.date().isoformat())
        self.assertEqual(self.runtime.blocked_domains(), ["first.example", "second.example"])
        for browser in ("chromium-session", "chrome-session"):
            self.runtime.handle_message({"op": "browser_snapshot", "browser_id": browser,
                                         "windows": [{"id": 1, "title": browser, "domain": "example.org"}]})
        self.assertEqual(len(self.runtime.browser_windows), 2)

    def test_legacy_parent_link_is_corrected_but_manual_links_survive(self):
        source = "app:chrome-service.example.org__-default"
        self.runtime.config.pop("link_schema", None)
        self.runtime.config["service_links"][source] = "site:example.org"
        agent.save_config(self.runtime.config)
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(source), "site:service.example.org")
        self.runtime.config["service_links"][source] = "site:example.org"
        agent.save_config(self.runtime.config)
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(source), "site:example.org")

    def test_unlink_web_app_stays_independent_after_restart(self):
        app = "app:chrome-example.org__-default"
        site = "site:example.org"
        self.runtime.handle_message({"op": "classify", "target_id": site, "category": "consumption"})
        self.runtime.reconcile_targets({app})
        self.assertEqual(self.runtime.resolve_target_id(app), site)
        self.assertTrue(self.runtime.handle_message({"op": "unlink", "target_id": app})["ok"])
        self.runtime.reconcile_targets({app})
        self.assertEqual(self.runtime.resolve_target_id(app), app)
        self.assertEqual(self.runtime.config["targets"][app]["quota_minutes"], 10)
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.assertEqual(self.runtime.resolve_target_id(app), app)
        self.assertTrue(self.runtime.handle_message({"op": "merge", "source": app, "destination": site})["ok"])
        self.assertEqual(self.runtime.resolve_target_id(app), site)

    def test_detach_main_member_keeps_history_with_remaining_group(self):
        for target in ("app:a", "app:b", "site:example.org"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        for source in ("app:a", "app:b"):
            self.runtime.handle_message({"op": "merge", "source": source, "destination": "site:example.org"})
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        self.runtime.store.add_times({"site:example.org": "consumption"}, 40, bucket, now.date().isoformat())
        self.assertTrue(self.runtime.handle_message({"op": "unlink", "target_id": "site:example.org"})["ok"])
        self.assertEqual(self.runtime.resolve_target_id("app:b"), "app:a")
        self.assertEqual(self.runtime.resolve_target_id("site:example.org"), "site:example.org")
        self.assertEqual(self.runtime.store.used_this_hour("app:a", bucket), 40)
        self.assertEqual(self.runtime.store.used_this_hour("site:example.org", bucket), 0)
        self.assertFalse(self.runtime.handle_message({"op": "unlink", "target_id": "site:example.org"})["ok"])
        self.assertFalse(self.runtime.handle_message({"op": "unlink", "target_id": "app:unknown"})["ok"])

    def test_timed_pause_survives_restart_and_resumes(self):
        self.assertTrue(self.runtime.handle_message({"op": "pause", "paused": True, "duration": "15"})["ok"])
        until = self.runtime.pause_until
        self.assertTrue(self.runtime.paused)
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.assertTrue(self.runtime.paused)
        self.runtime.resume_if_due(dt.datetime.fromtimestamp(until + 1).astimezone())
        self.assertFalse(self.runtime.paused)
        self.assertFalse(agent.load_config()["pause_state"]["active"])
        self.assertFalse(self.runtime.handle_message({"op": "pause", "paused": True, "duration": "invalid"})["ok"])

    def test_warning_once_and_can_be_disabled(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(481)
            self.runtime.tick(1)
            self.assertEqual(notify.call_count, 1)
            self.assertIn("Limit approaching", notify.call_args.args[0][-2])
        self.runtime.handle_message({"op": "set_warning", "enabled": False})
        self.runtime.warned_limits.clear()
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(1)
            notify.assert_not_called()

    def test_weekly_summary_keeps_missing_data_unknown(self):
        today = dt.date(2026, 9, 29)
        history = [{"day": "2026-09-29", "screen_seconds": 600, "productive": 5},
                   {"day": "2026-09-23", "screen_seconds": 300, "neutral": 2},
                   {"day": "2026-09-22", "screen_seconds": 400, "consumption": 3},
                   {"day": "2026-09-15", "screen_seconds": 9999}]
        weekly = agent.Runtime.weekly_summary(history, today)
        self.assertEqual(weekly["current"]["screen_seconds"], 900)
        self.assertEqual(weekly["previous"]["screen_seconds"], 400)
        self.assertEqual(weekly["screen_delta"], 500)
        self.assertEqual(weekly["current"]["recorded_days"], 2)
        self.assertIsNone(agent.Runtime.weekly_summary(history[:1], today)["screen_delta"])

    def test_suggestions_are_optional_and_dismissible(self):
        for target in ("site:a.example", "site:b.example"):
            self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
            self.runtime.config["site_names"][target[5:]] = "Same Service"
        self.runtime.tick(0)
        suggestions = self.runtime.latest_state["suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(len(self.runtime.config["targets"]), 2)
        self.runtime.handle_message({"op": "dismiss_suggestion", **suggestions[0]})
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["suggestions"], [])

    def test_data_export_backup_and_confirmed_clear(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        self.runtime.tick(12)
        response = self.runtime.handle_message({"op": "export_history"})
        self.assertTrue(response["ok"])
        exported = pathlib.Path(response["path"])
        self.assertIn("app:test,consumption,12", exported.read_text())
        self.assertIn("screen_time", exported.read_text())
        self.assertEqual(exported.stat().st_mode & 0o777, 0o600)
        response = self.runtime.handle_message({"op": "backup_settings"})
        self.assertIn("app:test", pathlib.Path(response["path"]).read_text())
        self.assertFalse(self.runtime.handle_message({"op": "clear_history"})["ok"])
        self.assertTrue(self.runtime.store.history())
        self.assertTrue(self.runtime.handle_message({"op": "clear_history", "confirm": True})["ok"])
        self.assertEqual(self.runtime.store.history(), [])
        self.assertIn("app:test", self.runtime.config["targets"])
        self.assertTrue(exported.exists())

    def test_detached_entries_still_have_manual_suggestions(self):
        rows = [{"id": target, "name": "service.example", "configured": True}
                for target in ("app:chrome-service.example__-default", "site:service.example")]
        self.runtime.config["independent_targets"] = [row["id"] for row in rows]
        self.assertEqual(len(self.runtime.group_suggestions(rows)), 1)
        self.assertEqual(self.runtime.resolve_target_id(rows[0]["id"]), rows[0]["id"])
        self.runtime.config["dismissed_suggestions"] = ["|".join(sorted(row["id"] for row in rows))]
        self.assertEqual(self.runtime.group_suggestions(rows), [])

    def test_review_classification(self):
        self.runtime.tick(2)
        state = self.runtime.latest_state
        self.assertEqual(state["focused_id"], "app:test")
        self.assertEqual(state["tracked"][0]["category"], "unclassified")
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["visible_windows"], 0)
        self.assertTrue(self.runtime.handle_message({
            "op": "classify", "target_id": "app:test", "category": "productive"
        })["ok"])
        self.assertEqual(self.runtime.store.pending_targets(), [])
        self.assertEqual(self.runtime.config["targets"]["app:test"]["category"], "productive")

    def test_site_metadata_names_are_dynamic_and_persisted(self):
        self.clients = [{"app_id": "chromium", "window_title": "Workspace - Chromium", "address": "0x123"}]
        self.runtime.handle_message({"op": "browser_snapshot", "windows": [
            {"id": 1, "title": "Workspace", "domain": "tools.example.org", "site_name": "New Service"}
        ]})
        self.runtime.tick(1)
        row = self.runtime.latest_state["tracked"][0]
        self.assertEqual(row["id"], "site:tools.example.org")
        self.assertEqual(row["name"], "New Service")
        self.assertEqual(agent.load_config()["site_names"]["tools.example.org"], "New Service")
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["name"], "New Service")

    def test_exclude_and_track_again(self):
        self.runtime.tick(2)
        self.assertTrue(self.runtime.store.pending_targets())
        self.assertTrue(self.runtime.handle_message({"op": "exclude", "target_id": "app:test"})["ok"])
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["tracked"], [])
        self.assertEqual(self.runtime.store.pending_targets(), [])
        self.assertEqual(self.runtime.latest_state["ignored_targets"], ["app:test"])
        self.assertTrue(self.runtime.handle_message({"op": "unexclude", "target_id": "app:test"})["ok"])
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["category"], "unclassified")

    def test_focused_browser_uses_matching_site(self):
        self.clients = [{"app_id": "chromium", "window_title": "A post - Chromium", "address": "0x123"}]
        self.runtime.browser_windows = {"1": {"title": "A post", "domain": "x.com"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(1)
        self.assertEqual(self.runtime.latest_state["focused_id"], "site:x.com")
        self.assertEqual([row["id"] for row in self.runtime.latest_state["tracked"]], ["site:x.com"])

    def test_web_app_and_browser_site_share_one_limit_and_close_correct_window(self):
        app_id = "app:chrome-x.com__-default"
        site_id = "site:x.com"
        self.runtime.config["targets"][app_id] = {
            "name": "chrome-x.com__-default", "category": "consumption", "quota_minutes": 1,
            "limit_action": "close",
        }
        self.runtime.config["targets"][site_id] = {
            "name": "x.com", "category": "consumption", "quota_minutes": 1,
            "limit_action": "close",
        }
        now = dt.datetime.now().astimezone()
        bucket = agent.current_hour_bucket(now)
        day = now.date().isoformat()
        self.runtime.store.add_times({app_id: "consumption"}, 20, bucket, day)
        self.runtime.store.add_times({site_id: "consumption"}, 20, bucket, day)
        self.clients = [
            {"app_id": "chrome-x.com__-default", "window_title": "X", "address": "0x123"},
            {"app_id": "chromium", "window_title": "X post - Chromium", "address": "0x456"},
        ]
        self.runtime.browser_windows = {"1": {"title": "X post", "domain": "x.com"}}
        self.runtime.last_browser_snapshot = time.monotonic()
        self.runtime.tick(20)
        rows = self.runtime.latest_state["tracked"]
        self.assertEqual([row["id"] for row in rows], [site_id])
        self.assertEqual(rows[0]["visible_windows"], 2)
        self.assertEqual(rows[0]["used_seconds"], 60)
        self.assertEqual(rows[0]["remaining_seconds"], 0)
        self.assertEqual([client["address"] for client in self.closed], ["0x123"])
        self.assertEqual(self.runtime.blocked_domains(), ["x.com"])
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["service_links"][app_id], site_id)
        self.assertTrue(rows[0]["linked"])
        self.assertEqual(self.runtime.store.used_this_hour(app_id, bucket), 0)
        self.assertTrue(self.runtime.handle_message({
            "op": "set_quota", "target_id": app_id, "quota_minutes": 5,
        })["ok"])
        self.assertEqual(self.runtime.config["targets"][site_id]["quota_minutes"], 5)

    def test_web_app_only_settings_become_site_settings(self):
        app_id = "app:chrome-youtube.com__-default"
        self.runtime.config["targets"][app_id] = {
            "name": "chrome-youtube.com__-default", "category": "consumption", "quota_minutes": 7,
        }
        self.runtime.reconcile_targets()
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["targets"]["site:youtube.com"], {
            "name": "youtube.com", "category": "consumption", "quota_minutes": 7,
        })
        self.assertEqual(self.runtime.config["service_links"][app_id], "site:youtube.com")

    def test_site_settings_win_when_linking_an_existing_web_app(self):
        app_id = "app:chrome-beeper.com__-default"
        site_id = "site:beeper.com"
        self.runtime.config["targets"][app_id] = {"name": "Beeper", "category": "consumption", "quota_minutes": 5}
        self.runtime.config["targets"][site_id] = {"name": "beeper.com", "category": "neutral", "quota_minutes": 12}
        with mock.patch.object(agent, "app_display_name", return_value="Beeper"):
            self.runtime.reconcile_targets()
        self.assertNotIn(app_id, self.runtime.config["targets"])
        self.assertEqual(self.runtime.config["targets"][site_id]["category"], "neutral")
        self.assertEqual(self.runtime.config["targets"][site_id]["quota_minutes"], 12)

    def test_native_app_names_do_not_create_links(self):
        with mock.patch.object(agent, "desktop_app_domains", return_value={}):
            self.assertEqual(agent.service_site_for_app("beeper"), "")
            self.assertEqual(agent.service_site_for_app("chromium"), "")

    def test_desktop_launcher_url_links_app_without_name_match(self):
        applications = pathlib.Path(self.temp.name) / "data" / "applications"
        applications.mkdir(parents=True)
        (applications / "calendar.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=My Calendar\n"
            "StartupWMClass=CalendarApp\nExec=chromium --app=https://calendar.example.com/home\n"
        )
        agent.desktop_app_domains.cache_clear()
        self.addCleanup(agent.desktop_app_domains.cache_clear)
        with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(applications.parent), "XDG_DATA_DIRS": ""}):
            self.assertEqual(agent.service_site_for_app("calendarapp"), "site:calendar.example.com")

    def test_all_visible_apps_accrue_time_without_focus(self):
        self.clients = [
            {"app_id": "First", "window_title": "First", "address": "0x123"},
            {"app_id": "Second", "window_title": "Second", "address": "0x456"},
        ]
        self.runtime.tick(10)
        rows = {row["id"]: row for row in self.runtime.latest_state["tracked"]}
        self.assertEqual(set(rows), {"app:first", "app:second"})
        self.assertTrue(rows["app:first"]["focused"])
        self.assertFalse(rows["app:second"]["focused"])
        self.assertEqual(rows["app:second"]["visible_windows"], 1)
        self.assertGreaterEqual(rows["app:second"]["today_seconds"], 10)

    def test_consumption_limit_and_pause(self):
        self.runtime.handle_message({"op": "classify", "target_id": "app:test", "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": "app:test", "quota_minutes": 1})
        self.runtime.tick(61)
        self.assertEqual(self.runtime.latest_state["tracked"][0]["remaining_seconds"], 0)
        self.assertEqual(len(self.closed), 1)
        self.runtime.handle_message({"op": "pause", "paused": True})
        self.runtime.tick(1)
        self.assertFalse(self.runtime.latest_state["working"])
        self.assertEqual(len(self.closed), 1)

    def test_screen_time_counts_overlapping_apps_once_and_survives_restart(self):
        self.clients.append({"app_id": "Second", "window_title": "Second", "address": "0x456"})
        self.runtime.tick(10)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 10)
        self.assertEqual(sum(row["today_seconds"] for row in self.runtime.latest_state["tracked"]), 20)
        started = self.runtime.latest_state["today"]["screen_started_at"]
        self.runtime.store.db.close()
        self.runtime = agent.Runtime()
        self.runtime.tick(5)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 15)
        self.assertEqual(self.runtime.latest_state["today"]["screen_started_at"], started)

    def test_screen_time_stops_when_tracking_is_inactive(self):
        self.runtime.tick(3)
        for locked, idle in [(True, False), (False, True)]:
            with mock.patch.object(agent, "session_status", return_value=(locked, idle)):
                self.runtime.tick(10)
        with mock.patch.object(agent, "in_work_hours", return_value=False):
            self.runtime.tick(10)
        self.runtime.paused = True
        self.runtime.tick(10)
        self.runtime.paused = False
        self.runtime.config["ignored_targets"] = ["app:test"]
        self.runtime.tick(10)
        self.clients = []
        self.runtime.tick(10)
        self.assertEqual(self.runtime.latest_state["today"]["screen_seconds"], 3)

    def test_screen_time_keeps_legacy_history_unknown_and_new_days_separate(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        with self.runtime.store.db:
            self.runtime.store.db.execute(
                "INSERT INTO daily_usage VALUES(?, 'app:test', 'neutral', 60)", (yesterday,))
        self.runtime.tick(7)
        history = {row["day"]: row for row in self.runtime.store.history()}
        self.assertNotIn("screen_seconds", history[yesterday])
        self.assertEqual(history[dt.date.today().isoformat()]["screen_seconds"], 7)
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        self.runtime.store.add_times({}, 10, tomorrow, tomorrow)
        self.assertEqual(self.runtime.store.history()[-1]["screen_seconds"], 0)

    def test_limit_action_is_per_target_and_defaults_to_close(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.assertFalse(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "unknown"
        })["ok"])
        self.assertTrue(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "keep_open"
        })["ok"])
        self.runtime.tick(61)
        self.assertEqual(self.closed, [])
        self.assertEqual(self.runtime.latest_state["tracked"][0]["limit_action"], "keep_open")
        self.assertTrue(self.runtime.handle_message({
            "op": "set_limit_action", "target_id": target, "action": "close"
        })["ok"])
        self.runtime.tick(0)
        self.assertEqual(len(self.closed), 1)

    def test_notify_action_sends_one_alert_per_hour(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 1})
        self.runtime.handle_message({"op": "set_limit_action", "target_id": target, "action": "notify"})
        with mock.patch.object(agent.subprocess, "Popen") as notify:
            self.runtime.tick(61)
            self.runtime.tick(1)
        self.assertEqual(self.closed, [])
        notify.assert_called_once()
        args = notify.call_args.args[0]
        self.assertIn("Time limit reached · Test", args)
        self.assertIn("1 min hourly limit", args[-1])

    def test_reclassification_keeps_quota_edit(self):
        target = "app:test"
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "productive"})
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "consumption"})
        self.runtime.handle_message({"op": "set_quota", "target_id": target, "quota_minutes": 17})
        self.runtime.handle_message({"op": "classify", "target_id": target, "category": "neutral"})
        self.assertEqual(self.runtime.config["targets"][target]["category"], "neutral")
        self.assertEqual(self.runtime.config["targets"][target]["quota_minutes"], 17)

    def test_today_does_not_reuse_yesterdays_totals(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        with self.runtime.store.db:
            self.runtime.store.db.execute(
                "INSERT INTO daily_usage VALUES(?,?,?,?)", (yesterday, "app:test", "productive", 600)
            )
        self.clients = []
        self.runtime.tick(0)
        self.assertEqual(self.runtime.latest_state["today"]["day"], dt.date.today().isoformat())
        self.assertEqual(self.runtime.latest_state["today"].get("productive", 0), 0)

    def test_schedule_edits_and_overnight_hours(self):
        schedule = {"weekdays": [0], "start": "22:00", "end": "02:00"}
        self.assertTrue(self.runtime.handle_message({"op": "set_schedule", "schedule": schedule})["ok"])
        self.assertEqual(self.runtime.config["schedule"], schedule)
        monday = dt.datetime(2026, 9, 28, 23, 0)
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(monday, schedule))
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(monday + dt.timedelta(hours=2), schedule))
        self.assertFalse(ORIGINAL_IN_WORK_HOURS(monday + dt.timedelta(hours=4), schedule))
        self.assertFalse(self.runtime.handle_message({
            "op": "set_schedule", "schedule": {"weekdays": [7], "start": "08:00", "end": "17:00"}
        })["ok"])

    def test_all_day_schedule_respects_selected_days(self):
        schedule = {"weekdays": [0], "start": "00:00", "end": "00:00"}
        self.assertTrue(self.runtime.handle_message({"op": "set_schedule", "schedule": schedule})["ok"])
        self.assertEqual(agent.load_config()["schedule"], schedule)
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 28, 0, 0), schedule))
        self.assertTrue(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 28, 23, 59), schedule))
        self.assertFalse(ORIGINAL_IN_WORK_HOURS(dt.datetime(2026, 9, 29, 0, 0), schedule))

    def test_system_portal_can_be_reviewed(self):
        portal = {"class": "xdg-desktop-portal-gtk", "address": "0x999",
                  "workspace": {"id": 1}, "size": [400, 300]}
        with mock.patch.object(agent, "hypr_json", side_effect=lambda command:
                               [{"activeWorkspace": {"id": 1}}] if command == "monitors" else [portal]):
            self.assertEqual(ORIGINAL_VISIBLE_CLIENTS(), [{
                "app_id": "xdg-desktop-portal-gtk", "window_title": "", "address": "0x999"
            }])
        day = dt.date.today().isoformat()
        self.runtime.store.add_times({"app:xdg-desktop-portal-gtk": "unclassified"}, 16, "bucket", day)
        self.runtime.tick(0)
        self.assertEqual(self.runtime.store.pending_targets(), ["app:xdg-desktop-portal-gtk"])
        self.assertTrue(any(row["id"] == "app:xdg-desktop-portal-gtk"
                            for row in self.runtime.latest_state["tracked"]))


if __name__ == "__main__":
    unittest.main()
